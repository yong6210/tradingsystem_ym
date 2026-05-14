#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.notification_dispatcher import NotificationDispatcher
from scripts.operation_report_io import atomic_write_text


BRIEF_SCRIPT = ROOT_DIR / "scripts" / "generate_operator_session_brief.py"


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
    return True if value else False


def _resolve_root_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _env_default(name: str, fallback: str) -> str:
    value = os.environ.get(name)
    if value is None:
        return fallback
    return value


def _env_flag(name: str) -> bool:
    return _env_default(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _default_state_file(*, brief_mode: str, channel: str) -> Path:
    mode_slug = brief_mode.replace("-", "_")
    channel_slug = channel.replace("-", "_")
    return ROOT_DIR / "reports" / "operations" / "operator_session_briefs" / f"last_alert_state_{mode_slug}_{channel_slug}.json"


def _default_latest_run_file(*, brief_mode: str) -> Path:
    mode_slug = brief_mode.replace("-", "_")
    return ROOT_DIR / "reports" / "operations" / "operator_session_briefs" / f"latest_operator_session_brief_{mode_slug}.json"


def _default_lock_file(*, brief_mode: str) -> Path:
    mode_slug = brief_mode.replace("-", "_")
    return ROOT_DIR / "reports" / "operations" / "operator_session_briefs" / f"operator_session_brief_{mode_slug}.lock"


def _try_acquire_lock(path: Path) -> int | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    return fd


def _release_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or read the latest operator session brief and send a concise handoff message when state changes."
    )
    parser.add_argument("--symbol", default=_env_default("OPERATOR_BRIEF_SYMBOL", "BTCUSDC"))
    parser.add_argument("--universe", default=_env_default("OPERATOR_BRIEF_UNIVERSE", "usdc_perp_top30"))
    parser.add_argument("--days", type=int, default=int(_env_default("OPERATOR_BRIEF_DAYS", "7")))
    parser.add_argument("--portfolio-limit", type=int, default=int(_env_default("OPERATOR_BRIEF_PORTFOLIO_LIMIT", "5")))
    parser.add_argument("--intent-limit", type=int, default=int(_env_default("OPERATOR_BRIEF_INTENT_LIMIT", "5")))
    parser.add_argument("--reconcile-limit", type=int, default=int(_env_default("OPERATOR_BRIEF_RECONCILE_LIMIT", "5")))
    parser.add_argument(
        "--state-file",
        default=_env_default("OPERATOR_BRIEF_STATE_FILE", ""),
    )
    parser.add_argument(
        "--latest-run-file",
        default=_env_default("OPERATOR_BRIEF_LATEST_RUN_FILE", ""),
    )
    parser.add_argument("--lock-file", default=_env_default("OPERATOR_BRIEF_LOCK_FILE", ""))
    parser.add_argument(
        "--run-timeout-seconds",
        type=int,
        default=int(_env_default("OPERATOR_BRIEF_RUN_TIMEOUT_SECONDS", "90")),
    )
    parser.add_argument("--channel", choices=["discord", "system"], default=_env_default("OPERATOR_BRIEF_CHANNEL", "system"))
    parser.add_argument("--brief-mode", choices=["shift-start", "shift-end"], default=_env_default("OPERATOR_BRIEF_MODE", "shift-start"))
    parser.add_argument("--webhook-url", default=_env_default("OPERATOR_BRIEF_DISCORD_WEBHOOK_URL", ""))
    parser.add_argument("--allow-live-send", action="store_true")
    parser.add_argument("--force-send", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.allow_live_send and _env_flag("OPERATOR_BRIEF_ALLOW_LIVE_SEND"):
        args.allow_live_send = True
    if not args.force_send and _env_default("OPERATOR_BRIEF_FORCE_SEND", "0") == "1":
        args.force_send = True
    if not args.dry_run and _env_flag("OPERATOR_BRIEF_DRY_RUN"):
        args.dry_run = True
    return args


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"state file is invalid: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _run_brief(args: argparse.Namespace) -> dict[str, Any]:
    timeout_seconds = max(1, int(getattr(args, "run_timeout_seconds", 90) or 90))
    command = [
        sys.executable,
        str(BRIEF_SCRIPT),
        "--symbol",
        args.symbol,
        "--universe",
        args.universe,
        "--days",
        str(args.days),
        "--portfolio-limit",
        str(args.portfolio_limit),
        "--intent-limit",
        str(args.intent_limit),
        "--reconcile-limit",
        str(args.reconcile_limit),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(ROOT_DIR),
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = str(exc.stderr or "").strip()
        stdout = str(exc.stdout or "").strip()
        detail = stderr or stdout
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"brief script timed out after {timeout_seconds}s{suffix}") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"brief script failed: {stderr}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"brief script returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("brief payload must be an object")
    return payload


def _surface_strip_summary(payload: dict[str, Any] | None, *, surface_type: str = "generic") -> dict[str, str]:
    surface = dict(payload or {})
    if surface_type == "validation":
        summary = dict((surface.get("validation_report") or {}).get("approval_strip_summary") or {})
    else:
        summary = dict(surface.get("approval_strip_summary") or {})
    if summary:
        return {
            "approve_value": str(summary.get("approve_value") or "n/a"),
            "approve_reason": str(summary.get("approve_reason") or ""),
            "align_value": str(summary.get("align_value") or "n/a"),
            "align_reason": str(summary.get("align_reason") or ""),
            "act_value": str(summary.get("act_value") or "continue_runtime_monitoring"),
            "act_reason": str(summary.get("act_reason") or ""),
            "act_priority_level": str(summary.get("act_priority_level") or "monitor"),
            "primary_reason": str(summary.get("primary_reason") or ""),
        }
    return {
        "approve_value": str(surface.get("deployment_go_no_go") or surface.get("approval_topline_status") or "n/a"),
        "approve_reason": str(surface.get("deployment_message") or surface.get("approval_topline_summary_line") or ""),
        "align_value": str(surface.get("playbook_go_no_go") or surface.get("approval_topline_status") or "n/a"),
        "align_reason": str(surface.get("playbook_message") or surface.get("approval_topline_summary_line") or ""),
        "act_value": str(surface.get("playbook_action") or "continue_runtime_monitoring"),
        "act_reason": str(surface.get("playbook_message") or surface.get("deployment_message") or ""),
        "act_priority_level": "monitor",
        "primary_reason": str(surface.get("deployment_message") or surface.get("playbook_message") or ""),
    }


def _surface_summary_line(label: str, summary: dict[str, str]) -> str:
    return (
        f"- {label}: approve={summary.get('approve_value', 'n/a')} | "
        f"align={summary.get('align_value', 'n/a')} | "
        f"act={summary.get('act_value', 'continue_runtime_monitoring')}"
    )


def _display_candidate_status(status: Any) -> str:
    raw_status = str(status or "").strip()
    if raw_status == "ACTIONABLE_ENTRY":
        return "CONTEXT_REVIEW_SETUP"
    return raw_status


def _candidate_handoff_line(label: str, candidate: dict[str, Any] | None) -> str:
    item = dict(candidate or {})
    if not item:
        return f"- {label}: none"
    line = (
        f"- {label}: symbol={item.get('symbol') or 'unknown'} "
        f"| family={item.get('strategy_family') or 'unknown'} "
        f"| edge={item.get('edge_state') or 'unknown'} "
        f"| split={(item.get('entry_timing_focus') or 'none')}/{(item.get('execution_style_focus') or 'none')}"
    )
    if item.get("status"):
        line = f"{line} | status={_display_candidate_status(item.get('status'))}"
    if item.get("block_reason"):
        line = f"{line} | reason={item.get('block_reason')}"
    return line


def _review_target_line(label: str, target: dict[str, Any] | None) -> str:
    item = dict(target or {})
    if not item:
        return f"- {label}: none"
    line = (
        f"- {label}: action={item.get('action') or 'unknown'} "
        f"| target={item.get('symbol') or 'unknown'} "
        f"| variant={item.get('preferred_variant') or 'none'} "
        f"| status={_display_candidate_status(item.get('status')) or 'unknown'} "
        f"| family={item.get('strategy_family') or 'unknown'}"
    )
    if item.get("block_reason"):
        line = f"{line} | reason={item.get('block_reason')}"
    if item.get("focus_source"):
        line = f"{line} | focus={item.get('focus_source')}"
    if item.get("followup_command"):
        line = f"{line} | cmd={item.get('followup_command')}"
    return line


def _edge_experiment_focus_text(funnel: dict[str, Any]) -> str:
    return (
        f"validation_state={funnel.get('edge_state')} "
        f"| live_validation={funnel.get('edge_proof_state', 'unknown')}/{funnel.get('edge_claim_state', 'unknown')} "
        f"| closed={int(funnel.get('edge_closed_trade_count', 0) or 0)}/{int(funnel.get('edge_proof_goal_closed_trades', 0) or 0)} "
        f"| remaining_to_goal={int(funnel.get('remaining_closed_trades_to_edge_proof_goal', 0) or 0)} "
        f"| regime={funnel.get('edge_regime_dependency_state', 'not_available')} "
        f"| entry_timing={funnel.get('entry_timing_focus')} "
        f"| execution_style={funnel.get('execution_style_focus')} "
        f"| true_edge={float(funnel.get('edge_true_edge_ratio', 0.0) or 0.0):.4f} "
        f"| decay={float(funnel.get('edge_decay_rate', 0.0) or 0.0):.4f}"
    )


def _alert_state(brief: dict[str, Any]) -> dict[str, Any]:
    snapshot = brief.get("snapshot") or {}
    approval_strip = snapshot.get("approval_strip") or {}
    dashboard = snapshot.get("dashboard_summary") or {}
    validation = snapshot.get("validation_summary") or {}
    checklist = snapshot.get("checklist_summary") or {}
    dashboard_strip = _surface_strip_summary(dashboard, surface_type="dashboard")
    validation_strip = _surface_strip_summary(validation, surface_type="validation")
    checklist_strip = _surface_strip_summary(checklist, surface_type="checklist")
    kernel = snapshot.get("kernel_snapshot") or {}
    funnel = snapshot.get("signal_funnel_snapshot") or {}
    accepted_candidate = dict(funnel.get("representative_accepted_candidate") or {})
    blocked_candidate = dict(funnel.get("representative_blocked_candidate") or {})
    entry_target = dict(funnel.get("entry_timing_review_target") or {})
    execution_target = dict(funnel.get("execution_style_review_target") or {})
    sections = snapshot.get("operator_ui_sections") or {}
    review_followup = funnel.get("review_followup_ledger") or {}
    return {
        "symbol": str(brief.get("symbol") or ""),
        "universe": str(brief.get("universe") or ""),
        "channel": "",
        "brief_mode": "",
        "brief_status": str(brief.get("brief_status") or ""),
        "headline": str(brief.get("headline") or ""),
        "deployment_alignment": str(snapshot.get("deployment_alignment") or ""),
        "playbook_alignment": str(snapshot.get("playbook_alignment") or ""),
        "top_operator_action": str(dashboard.get("top_operator_action") or ""),
        "top_action_followup_command": str(
            funnel.get("top_action_followup_command") or dashboard.get("top_action_followup_command") or ""
        ),
        "dashboard_approve": str(dashboard_strip.get("approve_value") or ""),
        "dashboard_align": str(dashboard_strip.get("align_value") or ""),
        "dashboard_act": str(dashboard_strip.get("act_value") or ""),
        "validation_approve": str(validation_strip.get("approve_value") or ""),
        "validation_align": str(validation_strip.get("align_value") or ""),
        "validation_act": str(validation_strip.get("act_value") or ""),
        "checklist_approve": str(checklist_strip.get("approve_value") or ""),
        "checklist_align": str(checklist_strip.get("align_value") or ""),
        "checklist_act": str(checklist_strip.get("act_value") or ""),
        "kernel_verdict": str(kernel.get("kernel_verdict") or ""),
        "money_leak_r": float(kernel.get("money_leak_r") or 0.0),
        "strongest_drag_source": str(kernel.get("strongest_drag_source") or ""),
        "outcome_control_tier": str(kernel.get("outcome_control_tier") or ""),
        "rollout_recommendation": str(kernel.get("rollout_recommendation") or ""),
        "candidate_surface_priority": str(kernel.get("candidate_surface_priority") or ""),
        "approval_strip_approve": str(approval_strip.get("approve_value") or ""),
        "approval_strip_align": str(approval_strip.get("align_value") or ""),
        "approval_strip_act": str(approval_strip.get("act_value") or ""),
        "approval_strip_priority": str(approval_strip.get("act_priority_level") or ""),
        "research_action": str(funnel.get("research_action") or ""),
        "edge_state": str(funnel.get("edge_state") or ""),
        "edge_proof_state": str(funnel.get("edge_proof_state") or ""),
        "edge_claim_state": str(funnel.get("edge_claim_state") or ""),
        "edge_proof_goal_closed_trades": int(funnel.get("edge_proof_goal_closed_trades", 0) or 0),
        "remaining_closed_trades_to_edge_proof_goal": int(
            funnel.get("remaining_closed_trades_to_edge_proof_goal", 0) or 0
        ),
        "edge_closed_trade_count": int(funnel.get("edge_closed_trade_count", 0) or 0),
        "edge_regime_dependency_state": str(funnel.get("edge_regime_dependency_state") or ""),
        "edge_true_edge_ratio": float(funnel.get("edge_true_edge_ratio", 0.0) or 0.0),
        "edge_decay_rate": float(funnel.get("edge_decay_rate", 0.0) or 0.0),
        "edge_evolution_state": str(funnel.get("edge_evolution_state") or ""),
        "edge_evolution_action": str(funnel.get("edge_evolution_action") or ""),
        "edge_evolution_bias": str(funnel.get("edge_evolution_bias") or ""),
        "review_followup_status": str(review_followup.get("last_status") or ""),
        "review_followup_action": str(review_followup.get("last_action") or ""),
        "review_followup_entries": int(review_followup.get("recent_entry_count", 0) or 0),
        "review_followup_command": str(review_followup.get("last_followup_command") or ""),
        "entry_timing_focus": str(funnel.get("entry_timing_focus") or ""),
        "execution_style_focus": str(funnel.get("execution_style_focus") or ""),
        "accepted_candidate_symbol": str(accepted_candidate.get("symbol") or ""),
        "accepted_candidate_edge_state": str(accepted_candidate.get("edge_state") or ""),
        "accepted_candidate_entry_timing": str(accepted_candidate.get("entry_timing_focus") or ""),
        "accepted_candidate_execution_style": str(accepted_candidate.get("execution_style_focus") or ""),
        "blocked_candidate_symbol": str(blocked_candidate.get("symbol") or ""),
        "blocked_candidate_edge_state": str(blocked_candidate.get("edge_state") or ""),
        "blocked_candidate_entry_timing": str(blocked_candidate.get("entry_timing_focus") or ""),
        "blocked_candidate_execution_style": str(blocked_candidate.get("execution_style_focus") or ""),
        "entry_target_symbol": str(entry_target.get("symbol") or ""),
        "entry_target_variant": str(entry_target.get("preferred_variant") or ""),
        "entry_target_status": str(entry_target.get("status") or ""),
        "entry_target_family": str(entry_target.get("strategy_family") or ""),
        "entry_target_followup_command": str(entry_target.get("followup_command") or ""),
        "execution_target_symbol": str(execution_target.get("symbol") or ""),
        "execution_target_variant": str(execution_target.get("preferred_variant") or ""),
        "execution_target_status": str(execution_target.get("status") or ""),
        "execution_target_family": str(execution_target.get("strategy_family") or ""),
        "execution_target_followup_command": str(execution_target.get("followup_command") or ""),
        "top_family_bottleneck": str(funnel.get("top_family_bottleneck") or ""),
        "top_session_bottleneck": str(funnel.get("top_session_bottleneck") or ""),
        "ui_all_present": _safe_bool(sections.get("all_present")),
        "brief_report_path": str(brief.get("report_path") or ""),
        "snapshot_report_path": str(snapshot.get("report_path") or ""),
    }


def _changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return True
    keys = (
        "channel",
        "brief_mode",
        "brief_status",
        "headline",
        "deployment_alignment",
        "playbook_alignment",
        "top_operator_action",
        "top_action_followup_command",
        "dashboard_approve",
        "dashboard_align",
        "dashboard_act",
        "validation_approve",
        "validation_align",
        "validation_act",
        "checklist_approve",
        "checklist_align",
        "checklist_act",
        "kernel_verdict",
        "money_leak_r",
        "strongest_drag_source",
        "outcome_control_tier",
        "rollout_recommendation",
        "candidate_surface_priority",
        "approval_strip_approve",
        "approval_strip_align",
        "approval_strip_act",
        "approval_strip_priority",
        "research_action",
        "edge_state",
        "edge_proof_state",
        "edge_claim_state",
        "edge_proof_goal_closed_trades",
        "remaining_closed_trades_to_edge_proof_goal",
        "edge_closed_trade_count",
        "edge_regime_dependency_state",
        "edge_true_edge_ratio",
        "edge_decay_rate",
        "edge_evolution_state",
        "edge_evolution_action",
        "edge_evolution_bias",
        "review_followup_status",
        "review_followup_action",
        "review_followup_entries",
        "review_followup_command",
        "entry_timing_focus",
        "execution_style_focus",
        "accepted_candidate_symbol",
        "accepted_candidate_edge_state",
        "accepted_candidate_entry_timing",
        "accepted_candidate_execution_style",
        "blocked_candidate_symbol",
        "blocked_candidate_edge_state",
        "blocked_candidate_entry_timing",
        "blocked_candidate_execution_style",
        "entry_target_symbol",
        "entry_target_variant",
        "entry_target_status",
        "entry_target_family",
        "entry_target_followup_command",
        "execution_target_symbol",
        "execution_target_variant",
        "execution_target_status",
        "execution_target_family",
        "execution_target_followup_command",
        "top_family_bottleneck",
        "top_session_bottleneck",
        "ui_all_present",
    )
    return any(previous.get(key) != current.get(key) for key in keys)

def _render_shift_start_message(brief: dict[str, Any]) -> str:
    snapshot = brief.get("snapshot") or {}
    approval_strip = snapshot.get("approval_strip") or {}
    dashboard = snapshot.get("dashboard_summary") or {}
    validation = snapshot.get("validation_summary") or {}
    checklist = snapshot.get("checklist_summary") or {}
    dashboard_strip = _surface_strip_summary(dashboard, surface_type="dashboard")
    validation_strip = _surface_strip_summary(validation, surface_type="validation")
    checklist_strip = _surface_strip_summary(checklist, surface_type="checklist")
    kernel = snapshot.get("kernel_snapshot") or {}
    sections = snapshot.get("operator_ui_sections") or {}
    funnel = snapshot.get("signal_funnel_snapshot") or {}
    review_followup = funnel.get("review_followup_ledger") or {}
    top_action_command = str(funnel.get("top_action_followup_command") or "")
    top_action_suffix = f" | cmd={top_action_command}" if top_action_command else ""
    review_command = str(review_followup.get("last_followup_command") or "")
    review_suffix = f" | cmd={review_command}" if review_command else ""
    lines = [
        "Operator session handoff",
        f"- brief_status: {brief.get('brief_status')}",
        f"- headline: {brief.get('headline')}",
        (
            f"- approval_strip: approve={approval_strip.get('approve_value')} "
            f"| align={approval_strip.get('align_value')} "
            f"| act={approval_strip.get('act_value')} "
            f"| priority={approval_strip.get('act_priority_level')}"
        ),
        (
            f"- kernel: verdict={kernel.get('kernel_verdict')} "
            f"| money_leak_r={kernel.get('money_leak_r')} "
            f"| drag_source={kernel.get('strongest_drag_source')} "
            f"| control={kernel.get('outcome_control_tier')} "
            f"| rollout={kernel.get('rollout_recommendation')} "
            f"| candidate_surface={kernel.get('candidate_surface_priority')}"
        ),
        _surface_summary_line("dashboard_surface", dashboard_strip),
        _surface_summary_line("validation_surface", validation_strip),
        _surface_summary_line("checklist_surface", checklist_strip),
        f"- top_operator_action: {dashboard.get('top_operator_action')}{top_action_suffix}",
        (
            f"- validation/funnel: action={funnel.get('research_action')} "
            f"| {_edge_experiment_focus_text(funnel)} "
            f"| edge_evolution={funnel.get('edge_evolution_state')}:{funnel.get('edge_evolution_action')}:{funnel.get('edge_evolution_bias')} "
            f"| review_ledger={review_followup.get('last_status')}:{review_followup.get('last_action')}:{review_followup.get('recent_entry_count')} "
            f"| family_bottleneck={funnel.get('top_family_bottleneck')} "
            f"| session_bottleneck={funnel.get('top_session_bottleneck')}"
        ),
        f"- review_followup_ledger: status={review_followup.get('last_status') or 'none'} | action={review_followup.get('last_action') or 'none'} | entries={review_followup.get('recent_entry_count') or 0}{review_suffix}",
        _review_target_line("entry_timing_review_target", funnel.get("entry_timing_review_target")),
        _review_target_line("execution_style_review_target", funnel.get("execution_style_review_target")),
        _candidate_handoff_line("accepted_candidate_focus", funnel.get("representative_accepted_candidate")),
        _candidate_handoff_line("blocked_candidate_focus", funnel.get("representative_blocked_candidate")),
        f"- operator_ui_sections_ready: {sections.get('all_present')}",
        f"- brief_report: {brief.get('report_path') or 'missing'}",
        f"- snapshot_report: {snapshot.get('report_path') or 'missing'}",
    ]
    for step in brief.get("next_steps") or []:
        lines.append(f"- next_step: {step}")
    return "\n".join(lines)

def _render_shift_end_message(brief: dict[str, Any]) -> str:
    snapshot = brief.get("snapshot") or {}
    approval_strip = snapshot.get("approval_strip") or {}
    dashboard = snapshot.get("dashboard_summary") or {}
    validation = snapshot.get("validation_summary") or {}
    checklist = snapshot.get("checklist_summary") or {}
    dashboard_strip = _surface_strip_summary(dashboard, surface_type="dashboard")
    validation_strip = _surface_strip_summary(validation, surface_type="validation")
    checklist_strip = _surface_strip_summary(checklist, surface_type="checklist")
    kernel = snapshot.get("kernel_snapshot") or {}
    funnel = snapshot.get("signal_funnel_snapshot") or {}
    review_followup = funnel.get("review_followup_ledger") or {}
    top_action_command = str(funnel.get("top_action_followup_command") or "")
    top_action_suffix = f" | cmd={top_action_command}" if top_action_command else ""
    review_command = str(review_followup.get("last_followup_command") or "")
    review_suffix = f" | cmd={review_command}" if review_command else ""
    lines = [
        "Operator shift-end summary",
        f"- closing_status: {brief.get('brief_status')}",
        f"- closing_headline: {brief.get('headline')}",
        (
            f"- closing_approval_strip: approve={approval_strip.get('approve_value')} "
            f"| align={approval_strip.get('align_value')} "
            f"| act={approval_strip.get('act_value')} "
            f"| priority={approval_strip.get('act_priority_level')}"
        ),
        (
            f"- closing_kernel: verdict={kernel.get('kernel_verdict')} "
            f"| money_leak_r={kernel.get('money_leak_r')} "
            f"| drag_source={kernel.get('strongest_drag_source')} "
            f"| control={kernel.get('outcome_control_tier')} "
            f"| rollout={kernel.get('rollout_recommendation')} "
            f"| candidate_surface={kernel.get('candidate_surface_priority')}"
        ),
        (
            f"- closing_alignment: deployment={snapshot.get('deployment_alignment')} "
            f"| playbook={snapshot.get('playbook_alignment')}"
        ),
        _surface_summary_line("closing_dashboard_surface", dashboard_strip),
        _surface_summary_line("closing_validation_surface", validation_strip),
        _surface_summary_line("closing_checklist_surface", checklist_strip),
        f"- final_top_action: {dashboard.get('top_operator_action')}{top_action_suffix}",
        (
            f"- carryover_focus: validation={funnel.get('research_action')} "
            f"| {_edge_experiment_focus_text(funnel)} "
            f"| edge_evolution={funnel.get('edge_evolution_state')}:{funnel.get('edge_evolution_action')}:{funnel.get('edge_evolution_bias')} "
            f"| review_ledger={review_followup.get('last_status')}:{review_followup.get('last_action')}:{review_followup.get('recent_entry_count')} "
            f"| family_bottleneck={funnel.get('top_family_bottleneck')} "
            f"| session_bottleneck={funnel.get('top_session_bottleneck')}"
        ),
        f"- carryover_review_followup_ledger: status={review_followup.get('last_status') or 'none'} | action={review_followup.get('last_action') or 'none'} | entries={review_followup.get('recent_entry_count') or 0}{review_suffix}",
        _review_target_line("carryover_entry_timing_review_target", funnel.get("entry_timing_review_target")),
        _review_target_line("carryover_execution_style_review_target", funnel.get("execution_style_review_target")),
        _candidate_handoff_line("carryover_accepted_candidate", funnel.get("representative_accepted_candidate")),
        _candidate_handoff_line("carryover_blocked_candidate", funnel.get("representative_blocked_candidate")),
        f"- handoff_brief: {brief.get('report_path') or 'missing'}",
        f"- supporting_snapshot: {snapshot.get('report_path') or 'missing'}",
    ]
    for step in brief.get("next_steps") or []:
        lines.append(f"- carryover_step: {step}")
    return "\n".join(lines)


def _render_message(brief: dict[str, Any], *, brief_mode: str) -> str:
    if brief_mode == "shift-end":
        return _render_shift_end_message(brief)
    return _render_shift_start_message(brief)


def main() -> int:
    args = parse_args()
    state_file = (
        _resolve_root_path(args.state_file).resolve()
        if str(args.state_file).strip()
        else _default_state_file(brief_mode=args.brief_mode, channel=args.channel)
    )
    latest_run_file = (
        _resolve_root_path(args.latest_run_file).resolve()
        if str(args.latest_run_file).strip()
        else _default_latest_run_file(brief_mode=args.brief_mode)
    )
    lock_file = (
        _resolve_root_path(getattr(args, "lock_file", "")).resolve()
        if str(getattr(args, "lock_file", "")).strip()
        else _default_lock_file(brief_mode=args.brief_mode)
    )
    lock_fd = _try_acquire_lock(lock_file)
    if lock_fd is None:
        result = {
            "state_file": str(state_file),
            "latest_run_file": str(latest_run_file),
            "lock_file": str(lock_file),
            "channel": args.channel,
            "brief_mode": args.brief_mode,
            "changed": False,
            "allow_live_send": bool(args.allow_live_send),
            "force_send": bool(args.force_send),
            "dry_run": bool(args.dry_run),
            "notified": False,
            "reason": "operator_session_brief_already_running",
        }
        _write_json(latest_run_file, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    try:
        try:
            brief = _run_brief(args)
        except RuntimeError as exc:
            result = {
                "state_file": str(state_file),
                "latest_run_file": str(latest_run_file),
                "lock_file": str(lock_file),
                "channel": args.channel,
                "brief_mode": args.brief_mode,
                "changed": False,
                "allow_live_send": bool(args.allow_live_send),
                "force_send": bool(args.force_send),
                "dry_run": bool(args.dry_run),
                "notified": False,
                "reason": "brief_generation_failed",
                "error": str(exc),
            }
            _write_json(latest_run_file, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        current = _alert_state(brief)
        current["channel"] = args.channel
        current["brief_mode"] = args.brief_mode
        previous = _read_json(state_file)
        changed = _changed(previous, current)

        result: dict[str, Any] = {
            "state_file": str(state_file),
            "latest_run_file": str(latest_run_file),
            "lock_file": str(lock_file),
            "channel": args.channel,
            "brief_mode": args.brief_mode,
            "brief_report_path": brief.get("report_path"),
            "snapshot_report_path": (brief.get("snapshot") or {}).get("report_path"),
            "current": current,
            "previous": previous,
            "changed": changed,
            "allow_live_send": bool(args.allow_live_send),
            "force_send": bool(args.force_send),
            "dry_run": bool(args.dry_run),
            "notified": False,
        }

        message = _render_message(brief, brief_mode=args.brief_mode)
        result["message"] = message

        if not changed and not args.force_send:
            _write_json(state_file, current)
            _write_json(latest_run_file, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.dry_run:
            _write_json(state_file, current)
            _write_json(latest_run_file, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if not args.allow_live_send:
            result["delivery"] = {
                "channel": args.channel,
                "delivered": False,
                "skipped": True,
                "reason": "live_send_not_allowed",
            }
            _write_json(latest_run_file, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        settings = get_settings()
        if args.webhook_url.strip():
            settings.alert_discord_webhook_url = args.webhook_url.strip()

        dispatcher = NotificationDispatcher(settings)
        delivery = dispatcher.dispatch(
            channel=args.channel,
            alert_type=f"operator_session_brief_{args.brief_mode.replace('-', '_')}",
            symbol=str(brief.get("symbol") or args.symbol).upper(),
            payload={"message": message},
        )
        result["delivery"] = delivery
        result["notified"] = _safe_bool(delivery.get("delivered"))
        _write_json(state_file, current)
        _write_json(latest_run_file, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        _release_lock(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
