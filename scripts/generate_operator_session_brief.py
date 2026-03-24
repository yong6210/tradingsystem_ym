#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
SNAPSHOT_SCRIPT = ROOT_DIR / "scripts" / "collect_operator_surface_divergence_snapshot.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a markdown operator session brief from the latest operator surface divergence snapshot."
    )
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--portfolio-limit", type=int, default=5)
    parser.add_argument("--intent-limit", type=int, default=5)
    parser.add_argument("--reconcile-limit", type=int, default=5)
    parser.add_argument("--report-dir", default="reports/operations/operator_session_briefs")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _run_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(SNAPSHOT_SCRIPT),
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
    completed = subprocess.run(command, capture_output=True, text=True, cwd=str(ROOT_DIR))
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"snapshot script failed: {stderr}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"snapshot script returned invalid JSON: {completed.stdout}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("snapshot payload must be an object")
    return payload


def _brief_status(snapshot: dict[str, Any]) -> str:
    if not bool(((snapshot.get("operator_ui_sections") or {}).get("all_present"))):
        return "UI_REGRESSION_REVIEW"
    if str(snapshot.get("deployment_alignment") or "") == "DIVERGED":
        return "DEPLOYMENT_REVIEW_REQUIRED"
    if str(snapshot.get("playbook_alignment") or "") == "DIVERGED":
        return "PLAYBOOK_REVIEW_REQUIRED"
    return "ALIGNED_MONITOR"


def _approval_strip_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    approval_strip = snapshot.get("approval_strip") or {}
    if approval_strip:
        return approval_strip
    dashboard = snapshot.get("dashboard_summary") or {}
    return {
        "approve_value": "n/a",
        "align_value": str(snapshot.get("deployment_alignment") or "n/a").lower(),
        "act_value": str(dashboard.get("top_operator_action") or "continue_runtime_monitoring"),
        "act_priority_level": "monitor",
        "primary_reason": "",
        "approve_reason": "",
        "align_reason": "",
        "act_reason": "",
    }


def _surface_strip_summary(surface: dict[str, Any], *, surface_type: str = "generic") -> dict[str, str]:
    payload = dict(surface or {})
    if surface_type == "validation":
        summary = dict((payload.get("validation_report") or {}).get("approval_strip_summary") or {})
    else:
        summary = dict(payload.get("approval_strip_summary") or {})
    if summary:
        return {
            "approve_value": str(summary.get("approve_value") or "n/a"),
            "align_value": str(summary.get("align_value") or "n/a"),
            "act_value": str(summary.get("act_value") or "n/a"),
            "approve_reason": str(summary.get("approve_reason") or ""),
            "align_reason": str(summary.get("align_reason") or ""),
            "act_reason": str(summary.get("act_reason") or ""),
        }
    return {
        "approve_value": str(payload.get("deployment_go_no_go") or payload.get("approval_topline_status") or "n/a"),
        "align_value": str(payload.get("playbook_go_no_go") or payload.get("approval_topline_status") or "n/a"),
        "act_value": str(payload.get("playbook_action") or "continue_runtime_monitoring"),
        "approve_reason": str(payload.get("deployment_message") or payload.get("approval_topline_summary_line") or ""),
        "align_reason": str(payload.get("playbook_message") or payload.get("approval_topline_summary_line") or ""),
        "act_reason": str(payload.get("playbook_message") or payload.get("deployment_message") or ""),
    }


def _surface_summary_line(label: str, surface: dict[str, Any], *, surface_type: str = "generic", suffix: str = "") -> str:
    summary = _surface_strip_summary(surface, surface_type=surface_type)
    line = (
        f"- {label}: approve={summary.get('approve_value', 'n/a')} / "
        f"align={summary.get('align_value', 'n/a')} / "
        f"act={summary.get('act_value', 'n/a')}"
    )
    if suffix:
        line = f"{line} / {suffix}"
    return line


def _representative_candidate_line(label: str, candidate: dict[str, Any] | None) -> str:
    item = dict(candidate or {})
    if not item:
        return f"- {label}: none"
    line = (
        f"- {label}: {item.get('symbol') or 'unknown'} / "
        f"family={item.get('strategy_family') or 'unknown'} / "
        f"edge={item.get('edge_state') or 'unknown'} / "
        f"split={(item.get('entry_timing_focus') or 'none')}/{(item.get('execution_style_focus') or 'none')}"
    )
    if item.get("status"):
        line = f"{line} / status={item.get('status')}"
    if item.get("block_reason"):
        line = f"{line} / reason={item.get('block_reason')}"
    return line


def _experiment_review_target_line(label: str, target: dict[str, Any] | None) -> str:
    item = dict(target or {})
    if not item:
        return f"- {label}: none"
    line = (
        f"- {label}: action={item.get('action') or 'unknown'} / "
        f"target={item.get('symbol') or 'unknown'} / "
        f"variant={item.get('preferred_variant') or 'none'} / "
        f"status={item.get('status') or 'unknown'} / "
        f"family={item.get('strategy_family') or 'unknown'}"
    )
    if item.get("block_reason"):
        line = f"{line} / reason={item.get('block_reason')}"
    if item.get("focus_source"):
        line = f"{line} / focus={item.get('focus_source')}"
    if item.get("followup_command"):
        line = f"{line} / cmd={item.get('followup_command')}"
    return line


def _headline(snapshot: dict[str, Any], status: str) -> str:
    dashboard = snapshot.get("dashboard_summary") or {}
    validation = snapshot.get("validation_summary") or {}
    checklist = snapshot.get("checklist_summary") or {}
    approval_strip = _approval_strip_snapshot(snapshot)
    dashboard_strip = _surface_strip_summary(dashboard, surface_type="dashboard")
    validation_strip = _surface_strip_summary(validation, surface_type="validation")
    checklist_strip = _surface_strip_summary(checklist, surface_type="checklist")
    kernel = snapshot.get("kernel_snapshot") or {}
    kernel_verdict = str(kernel.get("kernel_verdict") or "")
    drag_source = str(kernel.get("strongest_drag_source") or "n/a")
    rollout = str(kernel.get("rollout_recommendation") or "n/a")
    candidate_surface_priority = str(kernel.get("candidate_surface_priority") or "normal_priority")
    prefix = (
        f"approval_strip: approve={approval_strip.get('approve_value', '')} | "
        f"align={approval_strip.get('align_value', '')} | "
        f"act={approval_strip.get('act_value', '')}"
    )
    if status == "UI_REGRESSION_REVIEW":
        return f"{prefix}; operator UI home-section regression review is required before trusting the home surface."
    if status == "DEPLOYMENT_REVIEW_REQUIRED":
        return (
            f"{prefix}; dashboard and validation/checklist disagree on deployment posture; "
            f"dashboard={dashboard_strip.get('approve_value', '')}, "
            f"validation={validation_strip.get('approve_value', '')}, "
            f"checklist={checklist_strip.get('approve_value', '')}."
        )
    if status == "PLAYBOOK_REVIEW_REQUIRED":
        return (
            f"{prefix}; deployment posture is aligned but playbook wording differs across surfaces; "
            "review operator wording drift before acting."
        )
    if kernel_verdict in {"hold", "manual_review", "watch"}:
        return (
            f"{prefix}; surface alignment is usable, but 5-second kernel still points to "
            f"{kernel_verdict}; drag_source={drag_source}, rollout={rollout}, "
            f"candidate_surface={candidate_surface_priority}."
        )
    return f"{prefix}; dashboard, validation, checklist, and operator UI coverage are aligned enough for normal monitoring."


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = payload["snapshot"]
    dashboard = snapshot["dashboard_summary"]
    validation = snapshot["validation_summary"]
    checklist = snapshot["checklist_summary"]
    sections = snapshot["operator_ui_sections"]
    funnel = snapshot["signal_funnel_snapshot"]

    lines: list[str] = []
    lines.append("# Operator Session Brief")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- universe: {payload['universe']}")
    lines.append(f"- days: {payload['days']}")
    lines.append(f"- brief_status: {payload['brief_status']}")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- summary: {payload['headline']}")
    approval_strip = _approval_strip_snapshot(snapshot)
    lines.append(
        f"- approval_strip: approve={approval_strip.get('approve_value', '')} | "
        f"align={approval_strip.get('align_value', '')} | "
        f"act={approval_strip.get('act_value', '')} | "
        f"priority={approval_strip.get('act_priority_level', '')}"
    )
    lines.append(f"- top_operator_action: {dashboard.get('top_operator_action', '')}")
    lines.append(f"- snapshot_report: {snapshot.get('report_path', '')}")
    lines.append("")
    lines.append("## Approval Strip")
    lines.append("")
    lines.append(f"- primary_reason: {approval_strip.get('primary_reason', '')}")
    lines.append(f"- approve_reason: {approval_strip.get('approve_reason', '')}")
    lines.append(f"- align_reason: {approval_strip.get('align_reason', '')}")
    lines.append(f"- act_reason: {approval_strip.get('act_reason', '')}")
    lines.append("")
    lines.append("## 5-Second Kernel")
    lines.append("")
    kernel = snapshot.get("kernel_snapshot") or {}
    lines.append(
        f"- verdict: {kernel.get('kernel_verdict', '')} | "
        f"money_leak_r={kernel.get('money_leak_r', '')} | "
        f"drag_source={kernel.get('strongest_drag_source', '')} | "
        f"approval_tier={kernel.get('outcome_control_tier', '')} | "
        f"rollout={kernel.get('rollout_recommendation', '')} | "
        f"candidate_surface_priority={kernel.get('candidate_surface_priority', '')}"
    )
    lines.append(
        f"- expected_vs_realized_r: expected_closed={kernel.get('expected_closed_r', '')} / "
        f"post_cost_closed={kernel.get('post_cost_closed_r', '')} / "
        f"delta={kernel.get('closed_post_cost_delta_r', '')}"
    )
    lines.append("")
    lines.append("## Surface Alignment")
    lines.append("")
    lines.append(f"- deployment_alignment: {snapshot.get('deployment_alignment', '')}")
    lines.append(f"- playbook_alignment: {snapshot.get('playbook_alignment', '')}")
    lines.append(_surface_summary_line("dashboard", dashboard, surface_type="dashboard", suffix=f"mode={dashboard.get('execution_mode', '')}"))
    lines.append(_surface_summary_line("validation", validation, surface_type="validation", suffix=f"approval_topline_status={validation.get('approval_topline_status', '')}"))
    lines.append(_surface_summary_line("checklist", checklist, surface_type="checklist", suffix=f"overall_status={checklist.get('overall_status', '')}"))
    lines.append("")
    lines.append("## Operator UI Coverage")
    lines.append("")
    lines.append(f"- all_present: {sections.get('all_present', False)}")
    for section in sections.get("present_sections", []):
        lines.append(f"- [PASS] {section}")
    for section in sections.get("missing_sections", []):
        lines.append(f"- [FAIL] {section}")
    lines.append("")
    lines.append("## Promotion / Funnel Snapshot")
    lines.append("")
    lines.append(f"- research_action: {funnel.get('research_action', '')}")
    lines.append(f"- shadow_experiment: {funnel.get('shadow_experiment', '')}")
    lines.append(f"- top_action_followup_command: {funnel.get('top_action_followup_command', '') or 'none'}")
    lines.append(
        f"- edge_experiment: state={funnel.get('edge_state', '')} | "
        f"entry_timing={funnel.get('entry_timing_focus', '')} | "
        f"execution_style={funnel.get('execution_style_focus', '')}"
    )
    lines.append(
        f"- edge_evolution: state={funnel.get('edge_evolution_state', '')} | "
        f"action={funnel.get('edge_evolution_action', '')} | "
        f"bias={funnel.get('edge_evolution_bias', '')} | "
        f"promotion={funnel.get('edge_evolution_promotion_axis', '')}/{funnel.get('edge_evolution_promotion_variant', '')}"
    )
    lines.append(
        f"- review_followup_ledger: status={dict(funnel.get('review_followup_ledger') or {}).get('last_status', 'none')} / "
        f"action={dict(funnel.get('review_followup_ledger') or {}).get('last_action', 'none')} / "
        f"entries={dict(funnel.get('review_followup_ledger') or {}).get('recent_entry_count', 0)} / "
        f"cmd={dict(funnel.get('review_followup_ledger') or {}).get('last_followup_command', '') or 'none'}"
    )
    lines.append(_experiment_review_target_line("entry_timing_review_target", funnel.get("entry_timing_review_target")))
    lines.append(_experiment_review_target_line("execution_style_review_target", funnel.get("execution_style_review_target")))
    lines.append(
        _representative_candidate_line(
            "representative_accepted_candidate",
            funnel.get("representative_accepted_candidate"),
        )
    )
    lines.append(
        _representative_candidate_line(
            "representative_blocked_candidate",
            funnel.get("representative_blocked_candidate"),
        )
    )
    lines.append(f"- governance_state: {funnel.get('governance_state', '')}")
    lines.append(f"- review_queue: {funnel.get('review_queue', '')}")
    lines.append(f"- remediation_queue: {funnel.get('remediation_queue', '')}")
    lines.append(f"- clearance_state: {funnel.get('clearance_state', '')}")
    lines.append(f"- reopen_queue: {funnel.get('reopen_queue', '')}")
    lines.append(f"- decision_brief: {funnel.get('decision_brief', '')}")
    lines.append(f"- auto_execution_stage: {funnel.get('auto_execution_stage', '')}")
    lines.append(f"- hard_gate_bottleneck: {funnel.get('hard_gate_bottleneck', '')}")
    lines.append(f"- top_family_bottleneck: {funnel.get('top_family_bottleneck', '')}")
    lines.append(f"- top_regime_bottleneck: {funnel.get('top_regime_bottleneck', '')}")
    lines.append(f"- top_session_bottleneck: {funnel.get('top_session_bottleneck', '')}")
    lines.append("")
    lines.append("## Next Steps")
    lines.append("")
    for step in payload.get("next_steps", []):
        lines.append(f"- {step}")
    lines.append("")
    lines.append("## Raw Payload")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    generated_at = _now()
    snapshot = _run_snapshot(args)
    brief_status = _brief_status(snapshot)
    headline = _headline(snapshot, brief_status)
    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbol": args.symbol.upper(),
        "universe": args.universe,
        "days": args.days,
        "brief_status": brief_status,
        "headline": headline,
        "next_steps": snapshot.get("next_steps") or [],
        "snapshot": snapshot,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"operator_session_brief_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
