#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.main import app
from scripts.operation_report_io import atomic_write_text


EXPECTED_OPERATOR_UI_SECTIONS = (
    "5-Second Operator Kernel",
    "Approval Strip",
    "Deferred Research / Promotion Stack",
    "Validation Case Inspector",
    "Runtime Quality Inspector",
    "Signal Funnel Inspector",
    "Alpha Research Inspector",
    "Policy / Lock Inspector",
    "Intent / Exposure Inspector",
    "Mode / Deployment Inspector",
    "Approval Alignment Inspector",
    "Data Freshness / Source Inspector",
    "Portfolio Candidate Inspector",
    "Report Navigation",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect a dry-run snapshot of dashboard/validation/checklist divergence plus operator UI section readiness."
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--universe", default="usdt_reliable_balanced_31")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--portfolio-limit", type=int, default=5)
    parser.add_argument("--intent-limit", type=int, default=5)
    parser.add_argument("--reconcile-limit", type=int, default=5)
    parser.add_argument("--full-dashboard", action="store_true")
    parser.add_argument("--report-dir", default="reports/operations/operator_surface_divergence")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(default)


def _required_json(response: Any, method: str, path: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise RuntimeError(f"{method} {path} failed with HTTP {response.status_code}: {response.text}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} {path} returned non-object payload")
    return payload


def _section_readiness(html: str) -> dict[str, Any]:
    present = [section for section in EXPECTED_OPERATOR_UI_SECTIONS if section in html]
    missing = [section for section in EXPECTED_OPERATOR_UI_SECTIONS if section not in html]
    return {
        "expected_sections": list(EXPECTED_OPERATOR_UI_SECTIONS),
        "present_sections": present,
        "missing_sections": missing,
        "all_present": not missing,
    }


def _alignment(values: list[str]) -> str:
    normalized = [value for value in values if value]
    if not normalized:
        return "UNKNOWN"
    return "ALIGNED" if len(set(normalized)) == 1 else "DIVERGED"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalized_approve_alignment_value(summary: dict[str, str], *, surface: dict[str, Any] | None = None) -> str:
    value = str(summary.get("approve_value") or "").strip().lower().replace("-", "_")
    act_value = str(summary.get("act_value") or "").strip()
    payload = dict(surface or {})
    blocking_failures = _safe_int(payload.get("blocking_failures"))
    manual_actions = _safe_int(payload.get("manual_actions"))
    if value in {"approval usable", "approval_usable", "go", "pass"}:
        return "approval_usable"
    if (
        value == "manual review first"
        and act_value == "proceed_with_configured_rollout"
        and blocking_failures <= 0
        and manual_actions <= 0
    ):
        return "approval_usable"
    if "no_go" in value or "no go" in value:
        return "no_go"
    return value or "unknown"


def _normalized_act_alignment_value(summary: dict[str, str]) -> str:
    value = str(summary.get("act_value") or "").strip()
    if value in {"continue_candidate_review_under_portfolio_caps", "proceed_with_configured_rollout"}:
        return "continue_configured_rollout"
    return value or "unknown"


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


def _surface_summary_line(label: str, summary: dict[str, str], *, suffix: str = "") -> str:
    detail = f" | {suffix}" if suffix else ""
    return (
        f"- {label}: approve={summary.get('approve_value', 'n/a')} | "
        f"align={summary.get('align_value', 'n/a')} | "
        f"act={summary.get('act_value', 'continue_runtime_monitoring')} | "
        f"priority={summary.get('act_priority_level', 'monitor')}{detail}"
    )


def _edge_evolution_summary_line(summary: dict[str, Any] | None) -> str:
    item = dict(summary or {})
    if not item:
        return "- edge_evolution: unavailable"
    return (
        f"- edge_evolution: state={item.get('evolution_state', 'insufficient_sample')} | "
        f"action={item.get('recommended_action', 'keep_current_baseline')} | "
        f"bias={item.get('allocation_bias', 'hold_current_baseline')} | "
        f"promotion={item.get('promotion_candidate_axis', 'none')}/{item.get('promotion_candidate_variant', 'none')}"
    )


def _edge_experiment_snapshot_line(funnel: dict[str, Any]) -> str:
    return (
        f"- live_validation: state={funnel.get('edge_state', '')} | "
        f"entry_timing={funnel.get('entry_timing_focus', '')} | "
        f"execution_style={funnel.get('execution_style_focus', '')} | "
        f"validation={funnel.get('edge_proof_state', 'unknown')}/{funnel.get('edge_claim_state', 'unknown')} | "
        f"closed={int(funnel.get('edge_closed_trade_count', 0) or 0)}/{int(funnel.get('edge_proof_goal_closed_trades', 0) or 0)} | "
        f"remaining_to_goal={int(funnel.get('remaining_closed_trades_to_edge_proof_goal', 0) or 0)} | "
        f"regime={funnel.get('edge_regime_dependency_state', 'not_available')} | "
        f"true_edge={float(funnel.get('edge_true_edge_ratio', 0.0) or 0.0):.4f} | "
        f"decay={float(funnel.get('edge_decay_rate', 0.0) or 0.0):.4f}"
    )


def _display_candidate_status(status: Any) -> str:
    raw_status = str(status or "").strip()
    if raw_status == "ACTIONABLE_ENTRY":
        return "CONTEXT_REVIEW_SETUP"
    return raw_status


def _representative_candidate_snapshot(row: dict[str, Any] | None, *, status: str) -> dict[str, Any] | None:
    item = dict(row or {})
    if not item:
        return None
    edge_focus = dict(item.get("edge_experiment_focus") or {})
    session_guidance = dict(item.get("session_guidance") or {})
    capital_allocator = dict(item.get("capital_allocator") or {})
    return {
        "symbol": str(item.get("symbol") or ""),
        "status": status,
        "strategy_family": str(item.get("strategy_family") or ""),
        "block_reason": str(item.get("block_reason") or ""),
        "edge_state": str(edge_focus.get("edge_state") or ""),
        "entry_timing_focus": str(edge_focus.get("entry_timing_preferred_variant") or ""),
        "execution_style_focus": str(edge_focus.get("execution_style_preferred_variant") or ""),
        "true_edge_ratio": round(float(edge_focus.get("true_edge_ratio", 0.0) or 0.0), 4),
        "session_state": str(session_guidance.get("state") or ""),
        "allocator_tier": str(capital_allocator.get("tier") or ""),
    }


def _representative_candidate_line(label: str, candidate: dict[str, Any] | None) -> str:
    item = dict(candidate or {})
    if not item:
        return f"- {label}: none"
    parts = [
        f"family={item.get('strategy_family') or 'unknown'}",
        f"edge={item.get('edge_state') or 'unknown'}",
        f"split={(item.get('entry_timing_focus') or 'none')}/{(item.get('execution_style_focus') or 'none')}",
    ]
    if item.get("status"):
        parts.append(f"status={_display_candidate_status(item.get('status'))}")
    if item.get("block_reason"):
        parts.append(f"reason={item.get('block_reason')}")
    return f"- {label}: {item.get('symbol') or 'unknown'} | " + " | ".join(parts)


def _split_review_followup_command(*, symbol: str, universe: str, days: int, action: str) -> str:
    return (
        f"./.venv/bin/python scripts/run_split_review_followup.py "
        f"--symbol {symbol.upper()} --universe {universe} --days {max(1, int(days))} --action {action}"
    )


def _experiment_review_target_snapshot(
    operator_action_priority: dict[str, Any] | None,
    *,
    target_key: str,
    preferred_key: str,
    action: str,
    universe: str,
    days: int,
) -> dict[str, Any] | None:
    priority = dict(operator_action_priority or {})
    context = dict(priority.get("experiment_context") or {})
    target = dict(context.get(target_key) or {})
    if not target:
        return None
    symbol = str(target.get("symbol") or "")
    return {
        "action": action,
        "preferred_variant": str(context.get(preferred_key) or "none"),
        "symbol": symbol,
        "status": str(target.get("status") or ""),
        "strategy_family": str(target.get("strategy_family") or ""),
        "block_reason": str(target.get("block_reason") or ""),
        "focus_source": str(target.get("focus_source") or ""),
        "followup_command": (
            _split_review_followup_command(
                symbol=symbol,
                universe=universe,
                days=days,
                action=action,
            )
            if symbol
            else ""
        ),
    }


def _experiment_review_target_line(label: str, target: dict[str, Any] | None) -> str:
    item = dict(target or {})
    if not item:
        return f"- {label}: none"
    parts = [
        f"action={item.get('action') or 'unknown'}",
        f"target={item.get('symbol') or 'unknown'}",
        f"variant={item.get('preferred_variant') or 'none'}",
        f"status={_display_candidate_status(item.get('status')) or 'unknown'}",
        f"family={item.get('strategy_family') or 'unknown'}",
    ]
    if item.get("block_reason"):
        parts.append(f"reason={item.get('block_reason')}")
    if item.get("focus_source"):
        parts.append(f"focus={item.get('focus_source')}")
    if item.get("followup_command"):
        parts.append(f"cmd={item.get('followup_command')}")
    return f"- {label}: " + " | ".join(parts)


def _kernel_verdict(
    *,
    validation_go_no_go: str,
    checklist_go_no_go: str,
    approval_tier: str,
    rollout_recommendation: str,
    money_leak_r: float,
    closed_post_cost_delta_r: float,
) -> str:
    if validation_go_no_go == "NO_GO" or checklist_go_no_go == "NO_GO":
        return "hold"
    if approval_tier == "downgrade_to_manual" or rollout_recommendation == "reduce":
        return "manual_review"
    if money_leak_r >= 0.25 or closed_post_cost_delta_r <= -0.15:
        return "watch"
    return "monitor"


def _candidate_surface_priority(kernel_verdict: str) -> str:
    if kernel_verdict in {"hold", "manual_review", "watch"}:
        return "context_only"
    return "normal_priority"


def _approval_strip_snapshot(
    *,
    dashboard: dict[str, Any],
    validation: dict[str, Any],
    checklist: dict[str, Any],
    operator_action_priority: dict[str, Any],
    deployment_alignment: str,
    playbook_alignment: str,
    kernel_verdict: str,
    outcome_control_tier: str,
    rollout_recommendation: str,
    money_leak_r: float,
    strongest_drag_source: str,
) -> dict[str, Any]:
    dashboard_strip = _surface_strip_summary(dashboard, surface_type="dashboard")
    validation_strip = _surface_strip_summary(validation, surface_type="validation")
    checklist_strip = _surface_strip_summary(checklist, surface_type="checklist")
    entries_allowed = _safe_bool(dashboard.get("new_entries_allowed", False))
    primary_reason = str(
        dashboard.get("blocking_reason_message")
        or validation_strip.get("primary_reason")
        or checklist_strip.get("primary_reason")
        or dashboard_strip.get("primary_reason")
        or "현재 운영 판단 근거가 없습니다."
    )

    approve_value = "approval usable"
    approve_reason = str(
        validation_strip.get("approve_reason")
        or checklist_strip.get("approve_reason")
        or dashboard_strip.get("approve_reason")
        or primary_reason
    )
    if kernel_verdict == "hold":
        approve_value = "validation/checklist no_go"
        approve_reason = " | ".join(
            [
                f"validation={validation_strip.get('approve_value') or 'n/a'}",
                f"checklist={checklist_strip.get('approve_value') or 'n/a'}",
                f"dashboard={dashboard_strip.get('approve_value') or 'n/a'}",
                approve_reason,
            ]
        )
    elif kernel_verdict == "manual_review":
        approve_value = "manual review first"
        approve_reason = " | ".join(
            [
                f"control={outcome_control_tier or 'n/a'}",
                f"rollout={rollout_recommendation or 'n/a'}",
                approve_reason,
            ]
        )
    elif kernel_verdict == "watch":
        approve_value = "watch approval drift"
        approve_reason = " | ".join(
            [
                f"money_leak_r={money_leak_r}",
                f"drag_source={strongest_drag_source or 'n/a'}",
                approve_reason,
            ]
        )

    align_value = "aligned"
    align_message = "dashboard / checklist / validation surface가 같은 방향을 가리키고 있습니다."
    if deployment_alignment == "DIVERGED" and playbook_alignment == "DIVERGED":
        align_value = "diverged"
        align_message = "dashboard / checklist / validation surface가 서로 다른 방향을 가리키고 있습니다."
    elif deployment_alignment == "DIVERGED":
        align_value = "approve_drift"
        align_message = "surface approve 방향은 갈라졌지만 act wording은 아직 크게 벗어나지 않았습니다."
    elif playbook_alignment == "DIVERGED":
        align_value = "act_drift"
        align_message = "surface approve 방향은 비슷하지만 act wording drift가 남아 있습니다."
    align_detail = " | ".join(
        [
            f"dashboard={dashboard_strip.get('approve_value') or 'n/a'}",
            f"checklist={checklist_strip.get('approve_value') or 'n/a'}",
            f"validation={validation_strip.get('approve_value') or 'n/a'}",
        ]
    )
    align_next_move = str(
        dashboard_strip.get("act_value")
        or validation_strip.get("act_value")
        or checklist_strip.get("act_value")
        or "approval strip next move unavailable"
    )

    next_actions = operator_action_priority.get("next_actions") or []
    next_action_summary = " | ".join(
        f"{row.get('action')} [{row.get('priority_level')}]"
        for row in next_actions
        if row.get("action")
    )
    act_value = str(operator_action_priority.get("top_action") or "continue_runtime_monitoring")
    act_reason = str(
        operator_action_priority.get("top_reason")
        or "server-side operator action priority unavailable; advisory only"
    )
    if next_action_summary:
        act_reason = f"{act_reason} | {next_action_summary}"

    return {
        "entries_allowed": entries_allowed,
        "primary_reason": primary_reason,
        "approve_value": approve_value,
        "approve_reason": approve_reason,
        "align_value": align_value,
        "align_reason": f"{align_message} | {align_detail} | next_move={align_next_move}",
        "align_next_move": align_next_move,
        "act_value": act_value,
        "act_reason": act_reason,
        "act_priority_level": str(operator_action_priority.get("priority_level") or "monitor"),
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Operator Surface Divergence Snapshot")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- universe: {payload['universe']}")
    lines.append(f"- days: {payload['days']}")
    lines.append(f"- deployment_alignment: {payload['deployment_alignment']}")
    lines.append(f"- playbook_alignment: {payload['playbook_alignment']}")
    lines.append("")
    lines.append("## 5-Second Kernel")
    lines.append("")
    kernel = payload["kernel_snapshot"]
    lines.append(
        f"- verdict: {kernel['kernel_verdict']} | "
        f"money_leak_r={kernel['money_leak_r']} | "
        f"drag_source={kernel['strongest_drag_source']} | "
        f"approval_tier={kernel['outcome_control_tier']} | "
        f"rollout={kernel['rollout_recommendation']} | "
        f"candidate_surface_priority={kernel['candidate_surface_priority']}"
    )
    lines.append(
        f"- expected_vs_realized_r: expected_closed={kernel['expected_closed_r']} / "
        f"post_cost_closed={kernel['post_cost_closed_r']} / "
        f"delta={kernel['closed_post_cost_delta_r']}"
    )
    lines.append("")
    lines.append("## Approval Strip")
    lines.append("")
    approval_strip = payload["approval_strip"]
    lines.append(
        f"- approve={approval_strip['approve_value']} | "
        f"align={approval_strip['align_value']} | "
        f"act={approval_strip['act_value']} | "
        f"priority={approval_strip['act_priority_level']}"
    )
    lines.append(f"- primary_reason: {approval_strip['primary_reason']}")
    lines.append(f"- approve_reason: {approval_strip['approve_reason']}")
    lines.append(f"- align_reason: {approval_strip['align_reason']}")
    lines.append(f"- act_reason: {approval_strip['act_reason']}")
    lines.append("")
    lines.append("## Dashboard / Validation / Checklist")
    lines.append("")
    dashboard = payload["dashboard_summary"]
    validation = payload["validation_summary"]
    checklist = payload["checklist_summary"]
    lines.append(
        _surface_summary_line(
            "dashboard",
            dashboard["approval_strip_summary"],
            suffix=(
                f"execution_mode={dashboard['execution_mode']} | "
                f"top_action={dashboard['top_operator_action']} | "
                f"top_action_cmd={dashboard.get('top_action_followup_command') or 'none'}"
            ),
        )
    )
    lines.append(
        _surface_summary_line(
            "validation",
            validation["approval_strip_summary"],
            suffix=f"approval_topline_status={validation['approval_topline_status']}",
        )
    )
    lines.append(
        _surface_summary_line(
            "checklist",
            checklist["approval_strip_summary"],
            suffix=f"overall_status={checklist['overall_status']}",
        )
    )
    lines.append("")
    lines.append("## Operator UI Sections")
    lines.append("")
    for section in payload["operator_ui_sections"]["present_sections"]:
        lines.append(f"- [PASS] {section}")
    for section in payload["operator_ui_sections"]["missing_sections"]:
        lines.append(f"- [FAIL] {section}")
    lines.append("")
    lines.append("## Signal Funnel Snapshot")
    lines.append("")
    funnel = payload["signal_funnel_snapshot"]
    lines.append(f"- research_action: {funnel['research_action']}")
    lines.append(f"- shadow_experiment: {funnel['shadow_experiment']}")
    lines.append(f"- top_action_followup_command: {funnel.get('top_action_followup_command') or 'none'}")
    lines.append(_edge_experiment_snapshot_line(funnel))
    lines.append(
        f"- edge_evolution: state={funnel.get('edge_evolution_state', '')} | "
        f"action={funnel.get('edge_evolution_action', '')} | "
        f"bias={funnel.get('edge_evolution_bias', '')} | "
        f"promotion={funnel.get('edge_evolution_promotion_axis', '')}/{funnel.get('edge_evolution_promotion_variant', '')}"
    )
    lines.append(
        f"- review_followup_ledger: status={dict(funnel.get('review_followup_ledger') or {}).get('last_status', 'none')} | "
        f"action={dict(funnel.get('review_followup_ledger') or {}).get('last_action', 'none')} | "
        f"entries={dict(funnel.get('review_followup_ledger') or {}).get('recent_entry_count', 0)} | "
        f"cmd={dict(funnel.get('review_followup_ledger') or {}).get('last_followup_command', '') or 'none'}"
    )
    lines.append(
        _experiment_review_target_line(
            "entry_timing_review_target",
            funnel.get("entry_timing_review_target"),
        )
    )
    lines.append(
        _experiment_review_target_line(
            "execution_style_review_target",
            funnel.get("execution_style_review_target"),
        )
    )
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
    lines.append(f"- governance_state: {funnel['governance_state']}")
    lines.append(f"- review_queue: {funnel['review_queue']}")
    lines.append(f"- remediation_queue: {funnel['remediation_queue']}")
    lines.append(f"- clearance_state: {funnel['clearance_state']}")
    lines.append(f"- reopen_queue: {funnel['reopen_queue']}")
    lines.append(f"- decision_brief: {funnel['decision_brief']}")
    lines.append(f"- auto_execution_stage: {funnel['auto_execution_stage']}")
    lines.append("")
    lines.append("## Next Steps")
    lines.append("")
    for step in payload["next_steps"]:
        lines.append(f"- {step}")
    lines.append("")
    lines.append("## Raw Payload")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    atomic_write_text(path, "\n".join(lines))


def main() -> int:
    args = parse_args()
    generated_at = _now()

    with TestClient(app) as client:
        dashboard = _required_json(
            client.get(
                "/execution/operator-dashboard",
                params={
                    "symbol": args.symbol,
                    "universe": args.universe,
                    "portfolio_limit": args.portfolio_limit,
                    "intent_limit": args.intent_limit,
                    "reconcile_limit": args.reconcile_limit,
                    "days": args.days,
                    "fast": not bool(args.full_dashboard),
                },
            ),
            "GET",
            "/execution/operator-dashboard",
        )
        validation = _required_json(
            client.post(
                "/validation/report",
                params={"symbol": args.symbol, "refresh": "false", "cache_fallback": "true"},
            ),
            "POST",
            "/validation/report",
        )
        checklist = _required_json(
            client.post(
                "/operations/checklist",
                params={
                    "symbol": args.symbol,
                    "universe": args.universe,
                    "limit": args.portfolio_limit,
                    "days": args.days,
                    "write_report": "false",
                },
            ),
            "POST",
            "/operations/checklist",
        )
        operator_ui_response = client.get(
            "/execution/operator-ui",
            params={"symbol": args.symbol, "universe": args.universe, "days": args.days},
        )
        if operator_ui_response.status_code != 200:
            raise RuntimeError(
                f"GET /execution/operator-ui failed with HTTP {operator_ui_response.status_code}: {operator_ui_response.text}"
            )
        operator_ui_html = operator_ui_response.text

    signal_funnel = dashboard.get("signal_funnel") or {}
    portfolio_summary = dashboard.get("portfolio_summary") or {}
    accepted_candidate_rows = list(portfolio_summary.get("accepted_candidates") or [])
    blocked_candidate_rows = list(portfolio_summary.get("blocked_candidates") or [])
    operator_action_priority = signal_funnel.get("operator_action_priority") or {}
    alpha_research_action = signal_funnel.get("alpha_research_recommended_action") or {}
    alpha_research_experiment = signal_funnel.get("alpha_research_top_shadow_experiment") or {}
    hard_block_summary = signal_funnel.get("hard_block_summary") or {}
    rollout_block_summary = signal_funnel.get("rollout_block_summary") or {}
    score_to_outcome_funnel = signal_funnel.get("score_to_outcome_funnel") or {}
    money_funnel = score_to_outcome_funnel.get("money_funnel") or {}
    historical_expected_r = money_funnel.get("historical_expected_r") or {}
    historical_realized_r = money_funnel.get("historical_realized_r") or {}
    historical_gap_r = money_funnel.get("historical_gap_r") or {}
    outcome_attribution = signal_funnel.get("outcome_attribution") or {}
    edge_experiment = signal_funnel.get("edge_experiment_review") or {}
    edge_evolution = signal_funnel.get("edge_evolution_rule") or {}
    review_followup_ledger = signal_funnel.get("review_followup_ledger") or {}
    outcome_control_trace = signal_funnel.get("outcome_control_trace") or {}
    rollout_recommendation = signal_funnel.get("rollout_recommendation") or {}
    family_bottlenecks = signal_funnel.get("family_bottlenecks") or []
    regime_bottlenecks = signal_funnel.get("regime_bottlenecks") or []
    session_bottlenecks = signal_funnel.get("session_bottlenecks") or []
    dashboard_strip = _surface_strip_summary(dashboard, surface_type="dashboard")
    validation_strip = _surface_strip_summary(validation, surface_type="validation")
    checklist_strip = _surface_strip_summary(checklist, surface_type="checklist")
    deployment_alignment = _alignment(
        [
            _normalized_approve_alignment_value(dashboard_strip, surface=dashboard),
            _normalized_approve_alignment_value(validation_strip, surface=validation),
            _normalized_approve_alignment_value(checklist_strip, surface=checklist),
        ]
    )
    playbook_alignment = _alignment(
        [
            _normalized_act_alignment_value(dashboard_strip),
            _normalized_act_alignment_value(validation_strip),
            _normalized_act_alignment_value(checklist_strip),
        ]
    )
    operator_ui_sections = _section_readiness(operator_ui_html)
    money_leak_r = float((historical_gap_r.get("submitted_to_filled") or 0.0))
    expected_closed_r = float((historical_expected_r.get("closed") or 0.0))
    post_cost_closed_r = float((historical_realized_r.get("post_cost_closed") or 0.0))
    closed_post_cost_delta_r = float((outcome_attribution.get("closed_post_cost_delta_r") or 0.0))
    strongest_drag_source = str(outcome_attribution.get("strongest_drag_source") or "")
    outcome_control_tier = str(
        outcome_control_trace.get("approval_penalty_tier")
        or outcome_control_trace.get("approval_penalty_status")
        or ""
    )
    rollout_recommendation_state = str(rollout_recommendation.get("recommendation") or "")
    kernel_verdict = _kernel_verdict(
        validation_go_no_go=str(validation.get("deployment_go_no_go") or ""),
        checklist_go_no_go=str(checklist.get("deployment_go_no_go") or ""),
        approval_tier=outcome_control_tier,
        rollout_recommendation=rollout_recommendation_state,
        money_leak_r=money_leak_r,
        closed_post_cost_delta_r=closed_post_cost_delta_r,
    )
    candidate_surface_priority = _candidate_surface_priority(kernel_verdict)
    approval_strip = _approval_strip_snapshot(
        dashboard=dashboard,
        validation=validation,
        checklist=checklist,
        operator_action_priority=operator_action_priority,
        deployment_alignment=deployment_alignment,
        playbook_alignment=playbook_alignment,
        kernel_verdict=kernel_verdict,
        outcome_control_tier=outcome_control_tier,
        rollout_recommendation=rollout_recommendation_state,
        money_leak_r=money_leak_r,
        strongest_drag_source=strongest_drag_source,
    )
    representative_accepted_candidate = _representative_candidate_snapshot(
        accepted_candidate_rows[0] if accepted_candidate_rows else None,
        status="CONTEXT_REVIEW_SETUP",
    )
    representative_blocked_candidate = _representative_candidate_snapshot(
        blocked_candidate_rows[0] if blocked_candidate_rows else None,
        status="BLOCKED_SETUP",
    )
    entry_timing_review_target = _experiment_review_target_snapshot(
        operator_action_priority,
        target_key="entry_timing_target",
        preferred_key="entry_timing_preferred_variant",
        action="run_entry_timing_split_review",
        universe=args.universe,
        days=args.days,
    )
    execution_style_review_target = _experiment_review_target_snapshot(
        operator_action_priority,
        target_key="execution_style_target",
        preferred_key="execution_style_preferred_variant",
        action="run_execution_style_split_review",
        universe=args.universe,
        days=args.days,
    )

    next_steps: list[str] = []
    if deployment_alignment == "DIVERGED":
        next_steps.append("dashboard / validation / checklist의 surface approve 방향을 함께 읽고 Approval Strip의 align summary를 먼저 확인한다.")
    if playbook_alignment == "DIVERGED":
        next_steps.append("surface act drift가 있으면 rollout 승인보다 wording/source drift를 먼저 점검한다.")
    if not operator_ui_sections["all_present"]:
        next_steps.append("누락된 operator UI 홈 섹션을 regression으로 보고 execution_operator_ui와 smoke test를 다시 확인한다.")
    if kernel_verdict == "hold":
        next_steps.append("5-Second Operator Kernel verdict가 hold면 promotion stack보다 validation/checklist rollout 금지 해석을 먼저 본다.")
    elif kernel_verdict == "manual_review":
        next_steps.append("5-Second Operator Kernel verdict가 manual_review면 outcome control과 rollout recommendation을 먼저 본다.")
    elif kernel_verdict == "watch":
        next_steps.append("5-Second Operator Kernel verdict가 watch면 money leak과 post-cost attribution drift를 먼저 본다.")
    if candidate_surface_priority == "context_only":
        next_steps.append("Top Opportunity / Portfolio Candidate surface는 context-only로 읽고 approval/alignment/checklist를 먼저 끝낸다.")
    edge_state = str(edge_experiment.get("edge_state") or "")
    if edge_state in {"fragile_edge", "watch_edge"}:
        preferred_timing = str(edge_experiment.get("entry_timing_preferred_variant") or "none")
        preferred_execution = str(edge_experiment.get("execution_style_preferred_variant") or "none")
        targeted_reviews = [
            f"{target.get('action')}->{target.get('symbol')}:{target.get('status')}:{target.get('strategy_family')}:{target.get('preferred_variant')}"
            for target in (entry_timing_review_target, execution_style_review_target)
            if target
        ]
        if targeted_reviews:
            next_steps.append(
                "edge experiment review가 약화 상태면 구조 변경보다 split review target을 먼저 본다: "
                + "; ".join(targeted_reviews)
                + "."
            )
        else:
            next_steps.append(
                "edge experiment review가 약화 상태면 구조 변경보다 split review를 먼저 본다: "
                f"timing={preferred_timing}, execution={preferred_execution}."
            )
    evolution_state = str(edge_evolution.get("evolution_state") or "")
    if evolution_state in {"reduce_candidate", "edge_kill_review", "promote_candidate"}:
        next_steps.append(
            "edge evolution rule이 follow-up 우선순위를 바꾼다: "
            f"state={evolution_state}, action={edge_evolution.get('recommended_action') or 'keep_current_baseline'}, "
            f"bias={edge_evolution.get('allocation_bias') or 'hold_current_baseline'}."
        )
    if str(review_followup_ledger.get("last_status") or "") in {"NO_TARGET", "NO_REVIEW_ACTION_AVAILABLE"}:
        next_steps.append(
            "recent review followup ledger가 runnable target을 못 잡았으니, split/evolution action보다 target contract와 command carryover를 먼저 확인한다."
        )
    if not next_steps:
        next_steps.append("surface alignment와 operator UI home-section coverage가 현재 dry-run 기준으로 안정적이다.")

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbol": args.symbol.upper(),
        "universe": args.universe,
        "days": args.days,
        "deployment_alignment": deployment_alignment,
        "playbook_alignment": playbook_alignment,
        "dashboard_summary": {
            "execution_mode": dashboard.get("execution_mode", ""),
            "new_entries_allowed": dashboard.get("new_entries_allowed", False),
            "deployment_go_no_go": dashboard.get("deployment_go_no_go", ""),
            "playbook_action": dashboard.get("playbook_action", ""),
            "approval_strip_summary": dashboard_strip,
            "top_operator_action": (operator_action_priority.get("top_action") or ""),
            "top_action_followup_command": (operator_action_priority.get("top_action_followup_command") or ""),
            "recent_intents": len(dashboard.get("recent_intents") or []),
            "open_orders": len(dashboard.get("open_orders") or []),
            "open_positions": len(dashboard.get("open_positions") or []),
        },
        "validation_summary": {
            "deployment_go_no_go": validation.get("deployment_go_no_go", ""),
            "deployment_code": validation.get("deployment_code", ""),
            "deployment_message": validation.get("deployment_message", ""),
            "playbook_action": validation.get("playbook_action", ""),
            "approval_strip_summary": validation_strip,
            "approval_topline_status": validation.get("approval_topline_status", ""),
        },
        "checklist_summary": {
            "deployment_go_no_go": checklist.get("deployment_go_no_go", ""),
            "deployment_code": checklist.get("deployment_code", ""),
            "deployment_message": checklist.get("deployment_message", ""),
            "playbook_action": checklist.get("playbook_action", ""),
            "approval_strip_summary": checklist_strip,
            "overall_status": checklist.get("overall_status", ""),
            "blocking_failures": checklist.get("blocking_failures", 0),
            "manual_actions": checklist.get("manual_actions", 0),
            "warnings": checklist.get("warnings", 0),
        },
        "operator_ui_sections": operator_ui_sections,
        "approval_strip": approval_strip,
        "kernel_snapshot": {
            "kernel_verdict": kernel_verdict,
            "money_leak_r": money_leak_r,
            "expected_closed_r": expected_closed_r,
            "post_cost_closed_r": post_cost_closed_r,
            "closed_post_cost_delta_r": closed_post_cost_delta_r,
            "strongest_drag_source": strongest_drag_source,
            "outcome_control_tier": outcome_control_tier,
            "rollout_recommendation": rollout_recommendation_state,
            "candidate_surface_priority": candidate_surface_priority,
        },
        "signal_funnel_snapshot": {
            "research_action": (alpha_research_action.get("recommended_action") or ""),
            "shadow_experiment": (alpha_research_experiment.get("experiment_id") or ""),
            "top_action_followup_command": (operator_action_priority.get("top_action_followup_command") or ""),
            "edge_state": edge_state,
            "edge_proof_state": (dict(edge_experiment.get("edge_proof_posture") or {}).get("state") or ""),
            "edge_claim_state": (dict(edge_experiment.get("edge_proof_posture") or {}).get("claim_state") or ""),
            "edge_proof_goal_closed_trades": int(edge_experiment.get("edge_proof_goal_closed_trades", 0) or 0),
            "remaining_closed_trades_to_edge_proof_goal": int(
                edge_experiment.get("remaining_closed_trades_to_edge_proof_goal", 0) or 0
            ),
            "edge_closed_trade_count": int(
                dict(edge_experiment.get("daily_edge_kpis") or {}).get("closed_trade_count", 0) or 0
            ),
            "edge_regime_dependency_state": (
                dict(edge_experiment.get("daily_edge_kpis") or {}).get("regime_dependency_state") or ""
            ),
            "edge_true_edge_ratio": float(
                dict(edge_experiment.get("daily_edge_kpis") or {}).get(
                    "true_edge_ratio", edge_experiment.get("true_edge_ratio", 0.0)
                )
                or 0.0
            ),
            "edge_decay_rate": float(
                dict(edge_experiment.get("daily_edge_kpis") or {}).get(
                    "edge_decay_rate", edge_experiment.get("edge_decay_rate", 0.0)
                )
                or 0.0
            ),
            "edge_evolution_state": evolution_state,
            "edge_evolution_action": (edge_evolution.get("recommended_action") or ""),
            "edge_evolution_bias": (edge_evolution.get("allocation_bias") or ""),
            "edge_evolution_promotion_axis": (edge_evolution.get("promotion_candidate_axis") or ""),
            "edge_evolution_promotion_variant": (edge_evolution.get("promotion_candidate_variant") or ""),
            "review_followup_ledger": {
                "available": _safe_bool(review_followup_ledger.get("available", False)),
                "last_status": (review_followup_ledger.get("last_status") or ""),
                "last_action": (review_followup_ledger.get("last_action") or ""),
                "recent_entry_count": int(review_followup_ledger.get("recent_entry_count", 0) or 0),
                "last_followup_command": (review_followup_ledger.get("last_followup_command") or ""),
            },
            "entry_timing_focus": (edge_experiment.get("entry_timing_preferred_variant") or ""),
            "execution_style_focus": (edge_experiment.get("execution_style_preferred_variant") or ""),
            "entry_timing_review_target": entry_timing_review_target,
            "execution_style_review_target": execution_style_review_target,
            "representative_accepted_candidate": representative_accepted_candidate,
            "representative_blocked_candidate": representative_blocked_candidate,
            "governance_state": ((signal_funnel.get("promotion_governance") or {}).get("state") or ""),
            "review_queue": ((signal_funnel.get("promotion_review_queue") or {}).get("queue_state") or ""),
            "remediation_queue": ((signal_funnel.get("promotion_remediation_queue") or {}).get("queue_state") or ""),
            "clearance_state": ((signal_funnel.get("promotion_clearance_tracker") or {}).get("clearance_state") or ""),
            "reopen_queue": ((signal_funnel.get("promotion_reopen_queue") or {}).get("queue_state") or ""),
            "decision_brief": ((signal_funnel.get("promotion_decision_brief") or {}).get("brief_state") or ""),
            "auto_execution_stage": ((signal_funnel.get("auto_promotion_rollout_execution") or {}).get("execution_stage") or ""),
            "hard_gate_bottleneck": (hard_block_summary.get("top_reason") or ""),
            "softening_priority_queue": (signal_funnel.get("quality_softening_priorities") or []),
            "rollout_block_reason": (rollout_block_summary.get("top_reason") or ""),
            "top_family_bottleneck": ((family_bottlenecks[0] or {}).get("key") if family_bottlenecks else ""),
            "top_regime_bottleneck": ((regime_bottlenecks[0] or {}).get("key") if regime_bottlenecks else ""),
            "top_session_bottleneck": ((session_bottlenecks[0] or {}).get("key") if session_bottlenecks else ""),
        },
        "next_steps": next_steps,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"operator_surface_divergence_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = _display_path(report_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
