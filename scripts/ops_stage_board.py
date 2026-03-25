#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STAGE_FILE = ROOT_DIR / "reports/operations/stage_monitor/current_stage.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show the current operating stage from validation, checklist, and operator dashboard surfaces."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--alert-test-lookback-hours", type=int, default=24)
    parser.add_argument("--json", action="store_true", help="Print full JSON only.")
    parser.add_argument(
        "--stage-file",
        default=str(DEFAULT_STAGE_FILE),
        help="Write the latest stage snapshot to this path.",
    )
    parser.add_argument(
        "--no-write-stage",
        action="store_true",
        help="Do not persist the latest stage snapshot.",
    )
    return parser.parse_args()


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url += f"?{urlencode(query, doseq=True)}"
    request = Request(url=url, headers={"Accept": "application/json"}, method=method.upper())
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {payload}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method.upper()} {path} failed: {exc.reason}") from exc


def _write_stage_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _active_close_only(dashboard: dict[str, Any]) -> bool:
    locks = dashboard.get("active_locks")
    if not isinstance(locks, list):
        return False
    return any(str(item.get("reason_code") or "") == "close_only_active" for item in locks if isinstance(item, dict))


def _surface_strip_summary(payload: dict[str, Any] | None, *, surface_type: str = "generic") -> dict[str, str]:
    surface = dict(payload or {})
    if surface_type == "validation":
        summary = dict(surface.get("approval_strip_summary") or {})
        deployment_summary = dict(surface.get("deployment_approval_summary") or {})
    else:
        summary = dict(surface.get("approval_strip_summary") or {})
        deployment_summary = {}
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
        "approve_value": str(
            surface.get("deployment_go_no_go")
            or deployment_summary.get("deployment_go_no_go")
            or surface.get("approval_topline_status")
            or "n/a"
        ),
        "approve_reason": str(
            surface.get("deployment_message")
            or deployment_summary.get("deployment_message")
            or surface.get("approval_topline_summary_line")
            or ""
        ),
        "align_value": str(
            surface.get("playbook_go_no_go")
            or deployment_summary.get("playbook_go_no_go")
            or surface.get("approval_topline_status")
            or "n/a"
        ),
        "align_reason": str(
            surface.get("playbook_message")
            or deployment_summary.get("playbook_message")
            or surface.get("approval_topline_summary_line")
            or ""
        ),
        "act_value": str(
            surface.get("playbook_action")
            or deployment_summary.get("playbook_action")
            or "continue_runtime_monitoring"
        ),
        "act_reason": str(
            surface.get("playbook_message")
            or deployment_summary.get("playbook_message")
            or surface.get("deployment_message")
            or deployment_summary.get("deployment_message")
            or ""
        ),
        "act_priority_level": "monitor",
        "primary_reason": str(
            surface.get("deployment_message")
            or deployment_summary.get("deployment_message")
            or surface.get("playbook_message")
            or deployment_summary.get("playbook_message")
            or ""
        ),
    }


def _surface_summary_line(label: str, summary: dict[str, str]) -> str:
    return (
        f"{label}: approve={summary.get('approve_value', 'n/a')} | "
        f"align={summary.get('align_value', 'n/a')} | "
        f"act={summary.get('act_value', 'continue_runtime_monitoring')}"
    )


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _edge_experiment_summary(
    validation_report: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, Any] | None:
    dashboard_source = dict((((dashboard or {}).get("signal_funnel") or {}).get("edge_experiment_review") or {}))
    validation_source = dict((validation_report or {}).get("edge_experiment_review_summary") or {})
    source = dashboard_source or validation_source
    if not source:
        return None

    source_summary = dict(source.get("source_summary") or {})
    edge_proof_posture = dict(source.get("edge_proof_posture") or {})
    daily_edge_kpis = dict(source.get("daily_edge_kpis") or {})
    return {
        "available": bool(source.get("available", True)),
        "advisory_only": bool(source.get("advisory_only", True)),
        "edge_state": str(source.get("edge_state") or "insufficient_edge_measurement"),
        "summary": str(source.get("summary") or ""),
        "true_edge_ratio": round(_float(source.get("true_edge_ratio")), 4),
        "edge_decay_rate": round(_float(source.get("edge_decay_rate")), 4),
        "entry_timing_preferred_variant": str(
            source.get("entry_timing_preferred_variant") or source_summary.get("entry_timing_preferred_variant") or "none"
        ),
        "execution_style_preferred_variant": str(
            source.get("execution_style_preferred_variant")
            or source_summary.get("execution_style_preferred_variant")
            or "none"
        ),
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
            "focus": str(edge_proof_posture.get("focus") or ""),
            "summary": str(edge_proof_posture.get("summary") or ""),
        },
        "daily_edge_kpis": {
            "closed_trade_count": int(daily_edge_kpis.get("closed_trade_count", source.get("closed_trade_count", 0)) or 0),
            "sample_maturity_state": str(
                daily_edge_kpis.get("sample_maturity_state") or source.get("sample_maturity_state") or "unknown"
            ),
            "true_edge_ratio": round(_float(daily_edge_kpis.get("true_edge_ratio", source.get("true_edge_ratio"))), 4),
            "edge_decay_rate": round(_float(daily_edge_kpis.get("edge_decay_rate", source.get("edge_decay_rate"))), 4),
            "regime_dependency_state": str(
                daily_edge_kpis.get("regime_dependency_state") or source.get("regime_dependency_state") or "not_available"
            ),
        },
    }


def _edge_evolution_summary(
    validation_report: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, Any] | None:
    dashboard_source = dict((((dashboard or {}).get("signal_funnel") or {}).get("edge_evolution_rule") or {}))
    validation_source = dict((validation_report or {}).get("edge_evolution_rule_summary") or {})
    source = dashboard_source or validation_source
    if not source:
        return None
    return {
        "available": bool(source.get("available", True)),
        "advisory_only": bool(source.get("advisory_only", True)),
        "evolution_state": str(source.get("evolution_state") or "insufficient_sample"),
        "recommended_action": str(source.get("recommended_action") or "keep_current_baseline"),
        "allocation_bias": str(source.get("allocation_bias") or "hold_current_baseline"),
        "promotion_candidate_axis": str(source.get("promotion_candidate_axis") or "none"),
        "promotion_candidate_variant": str(source.get("promotion_candidate_variant") or "none"),
    }


def _review_followup_summary(
    validation_report: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, Any] | None:
    dashboard_source = dict((((dashboard or {}).get("signal_funnel") or {}).get("review_followup_ledger") or {}))
    validation_source = dict((validation_report or {}).get("review_followup_ledger_summary") or {})
    source = dashboard_source or validation_source
    if not source:
        return None
    return {
        "available": bool(source.get("available", False)),
        "last_status": str(source.get("last_status") or "none"),
        "last_action": str(source.get("last_action") or "none"),
        "recent_entry_count": int(source.get("recent_entry_count", 0) or 0),
        "last_followup_command": str(source.get("last_followup_command") or ""),
    }


def _edge_experiment_detail_parts(summary: dict[str, Any]) -> dict[str, Any]:
    posture = dict(summary.get("edge_proof_posture") or {})
    kpis = dict(summary.get("daily_edge_kpis") or {})
    return {
        "proof_state": str(posture.get("state") or "unknown"),
        "claim_state": str(posture.get("claim_state") or "unknown"),
        "proof_goal_closed_trades": int(summary.get("edge_proof_goal_closed_trades", 0) or 0),
        "remaining_closed_trades_to_edge_proof_goal": int(
            summary.get("remaining_closed_trades_to_edge_proof_goal", 0) or 0
        ),
        "closed_trade_count": int(kpis.get("closed_trade_count", 0) or 0),
        "true_edge_ratio": round(_float(kpis.get("true_edge_ratio", summary.get("true_edge_ratio"))), 4),
        "edge_decay_rate": round(_float(kpis.get("edge_decay_rate", summary.get("edge_decay_rate"))), 4),
        "regime_dependency_state": str(kpis.get("regime_dependency_state") or "not_available"),
    }


def _edge_experiment_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "edge_experiment: unavailable"
    detail = _edge_experiment_detail_parts(summary)
    return (
        f"edge_experiment: state={summary.get('edge_state', 'insufficient_edge_measurement')} | "
        f"entry_timing={summary.get('entry_timing_preferred_variant', 'none')} | "
        f"execution_style={summary.get('execution_style_preferred_variant', 'none')} | "
        f"proof={detail['proof_state']}/{detail['claim_state']} | "
        f"closes={detail['closed_trade_count']}/{detail['proof_goal_closed_trades']} | "
        f"remaining={detail['remaining_closed_trades_to_edge_proof_goal']} | "
        f"regime={detail['regime_dependency_state']} | "
        f"true_edge={detail['true_edge_ratio']:.4f} | "
        f"decay={detail['edge_decay_rate']:.4f}"
    )


def _edge_evolution_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "edge_evolution: unavailable"
    return (
        f"edge_evolution: state={summary.get('evolution_state', 'insufficient_sample')} | "
        f"action={summary.get('recommended_action', 'keep_current_baseline')} | "
        f"bias={summary.get('allocation_bias', 'hold_current_baseline')} | "
        f"promotion={summary.get('promotion_candidate_axis', 'none')}/{summary.get('promotion_candidate_variant', 'none')}"
    )


def _review_followup_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "review_followup_ledger: unavailable"
    return (
        f"review_followup_ledger: status={summary.get('last_status', 'none')} | "
        f"action={summary.get('last_action', 'none')} | "
        f"entries={int(summary.get('recent_entry_count', 0) or 0)} | "
        f"cmd={summary.get('last_followup_command', '') or 'none'}"
    )


_LINEAGE_TARGET_FAMILIES = {"sweep_reversal", "trend_continuation"}


def _representative_candidates(dashboard: dict[str, Any]) -> dict[str, Any]:
    portfolio = dict((dashboard or {}).get("portfolio_summary") or {})

    def _candidate(row: dict[str, Any] | None, *, status: str) -> dict[str, Any] | None:
        item = dict(row or {})
        if not item:
            return None
        focus = dict(item.get("edge_experiment_focus") or {})
        return {
            "symbol": str(item.get("symbol") or ""),
            "status": status,
            "strategy_family": str(item.get("strategy_family") or ""),
            "block_reason": str(item.get("block_reason") or ""),
            "edge_state": str(focus.get("edge_state") or "insufficient_edge_measurement"),
            "entry_timing_preferred_variant": str(focus.get("entry_timing_preferred_variant") or "none"),
            "execution_style_preferred_variant": str(focus.get("execution_style_preferred_variant") or "none"),
        }

    accepted_rows = list(portfolio.get("accepted_candidates") or [])
    blocked_rows = list(portfolio.get("blocked_candidates") or [])
    return {
        "accepted": _candidate(accepted_rows[0] if accepted_rows else None, status="ACTIONABLE_ENTRY"),
        "blocked": _candidate(blocked_rows[0] if blocked_rows else None, status="BLOCKED_SETUP"),
    }


def _representative_candidate_summary_line(label: str, candidate: dict[str, Any] | None) -> str:
    item = dict(candidate or {})
    if not item:
        return f"{label}: none"
    line = (
        f"{label}: {item.get('symbol') or 'unknown'} | "
        f"family={item.get('strategy_family') or 'unknown'} | "
        f"edge={item.get('edge_state') or 'insufficient_edge_measurement'} | "
        f"split={(item.get('entry_timing_preferred_variant') or 'none')}/{(item.get('execution_style_preferred_variant') or 'none')}"
    )
    if item.get("status"):
        line = f"{line} | status={item.get('status')}"
    if item.get("block_reason"):
        line = f"{line} | reason={item.get('block_reason')}"
    return line


def _split_review_followup_command(*, symbol: str, universe: str, days: int, action: str) -> str:
    return (
        f"./.venv/bin/python scripts/run_split_review_followup.py "
        f"--symbol {symbol.upper()} --universe {universe} --days {max(1, int(days))} --action {action}"
    )


def _experiment_review_target(
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


def _lineage_gate_ready(selected_trial_run_id: Any, trial_runs_written: Any) -> bool:
    return bool(selected_trial_run_id) or int(trial_runs_written or 0) > 0


def _candidate_gate_ready(
    representative_candidates: dict[str, Any] | None,
    entry_timing_review_target: dict[str, Any] | None,
    execution_style_review_target: dict[str, Any] | None,
) -> bool:
    accepted = dict((representative_candidates or {}).get("accepted") or {})
    accepted_family = str(accepted.get("strategy_family") or "").strip().lower()
    if accepted and accepted_family in _LINEAGE_TARGET_FAMILIES:
        return True

    for target in (entry_timing_review_target, execution_style_review_target):
        item = dict(target or {})
        family = str(item.get("strategy_family") or "").strip().lower()
        status = str(item.get("status") or "").strip().upper()
        if item and family in _LINEAGE_TARGET_FAMILIES and status.startswith("ACTIONABLE"):
            return True
    return False


def _edge_sample_gate_ready(edge_experiment_review: dict[str, Any] | None) -> bool:
    summary = dict(edge_experiment_review or {})
    if not summary:
        return False
    detail = _edge_experiment_detail_parts(summary)
    proof_goal = int(detail.get("proof_goal_closed_trades", 0) or 0)
    closed_count = int(detail.get("closed_trade_count", 0) or 0)
    return proof_goal > 0 and closed_count >= proof_goal


def _readiness_gates(
    *,
    selected_trial_run_id: Any,
    trial_runs_written: Any,
    representative_candidates: dict[str, Any] | None,
    entry_timing_review_target: dict[str, Any] | None,
    execution_style_review_target: dict[str, Any] | None,
    edge_experiment_review: dict[str, Any] | None,
) -> dict[str, Any]:
    lineage_ready = _lineage_gate_ready(selected_trial_run_id, trial_runs_written)
    candidate_ready = _candidate_gate_ready(
        representative_candidates,
        entry_timing_review_target,
        execution_style_review_target,
    )
    edge_sample_ready = _edge_sample_gate_ready(edge_experiment_review)
    all_ready = lineage_ready and candidate_ready and edge_sample_ready
    return {
        "lineage_gate_ready": lineage_ready,
        "candidate_gate_ready": candidate_ready,
        "edge_sample_gate_ready": edge_sample_ready,
        "all_ready": all_ready,
        "summary": (
            f"lineage={lineage_ready} | candidate={candidate_ready} | "
            f"edge_sample={edge_sample_ready} | all_ready={all_ready}"
        ),
    }


def _experiment_review_target_line(label: str, target: dict[str, Any] | None) -> str:
    item = dict(target or {})
    if not item:
        return f"{label}: none"
    line = (
        f"{label}: action={item.get('action') or 'unknown'} | "
        f"target={item.get('symbol') or 'unknown'} | "
        f"variant={item.get('preferred_variant') or 'none'} | "
        f"status={item.get('status') or 'unknown'} | "
        f"family={item.get('strategy_family') or 'unknown'}"
    )
    if item.get("block_reason"):
        line = f"{line} | reason={item.get('block_reason')}"
    if item.get("focus_source"):
        line = f"{line} | focus={item.get('focus_source')}"
    if item.get("followup_command"):
        line = f"{line} | cmd={item.get('followup_command')}"
    return line


def _stage_from_payload(
    validation_report: dict[str, Any],
    checklist: dict[str, Any],
    dashboard: dict[str, Any],
) -> str:
    deployment = validation_report.get("deployment_approval_summary") or {}
    playbook_go_no_go = str(deployment.get("playbook_go_no_go") or "").upper()
    selected_trial_run_id = (
        (
            validation_report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {}
        ).get("selected_trial_run_id")
    )
    sample_counts = (
        (validation_report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {}).get("sample_counts") or {}
    )
    eligible_closed_trades = int(sample_counts.get("eligible_closed_trades") or 0)
    trial_runs_written = int(sample_counts.get("trial_runs_written") or 0)
    close_only_active = _active_close_only(dashboard)

    if (
        dashboard.get("new_entries_allowed") is False
        or close_only_active
        or playbook_go_no_go == "NO_GO"
        or str(checklist.get("overall_status") or "").upper() == "FAIL"
    ):
        return "0_BLOCKED"
    if trial_runs_written == 0 and eligible_closed_trades > 0:
        return "1_SAMPLE_COLLECTION"
    if selected_trial_run_id is not None or trial_runs_written > 0:
        return "2_LINEAGE_READY"
    if playbook_go_no_go in {"MANUAL_REVIEW", "GO"}:
        return "3_APPROVAL_REVIEW"
    return "CHECK_MANUALLY"


def _stage_message_fields(
    stage: str,
    validation_report: dict[str, Any],
    checklist: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, str]:
    deployment = validation_report.get("deployment_approval_summary") or {}
    playbook_go_no_go = str(deployment.get("playbook_go_no_go") or "").upper()
    close_only_active = _active_close_only(dashboard)
    execution_status = str(
        ((validation_report.get("execution_degradation_advisory_summary") or {}).get("status") or "")
    ).lower()
    trial_writer_summary = validation_report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {}
    sample_counts = trial_writer_summary.get("sample_counts") or {}
    eligible_closed_trades = int(sample_counts.get("eligible_closed_trades") or 0)
    trial_runs_written = int(sample_counts.get("trial_runs_written") or 0)
    selected_trial_run_id = trial_writer_summary.get("selected_trial_run_id")

    blockers: list[str] = []
    if close_only_active:
        blockers.append("close_only_active")
    if playbook_go_no_go == "NO_GO":
        blockers.append("NO_GO")
    if execution_status == "manual_review":
        blockers.append("manual_review")

    if stage == "0_BLOCKED":
        return {
            "stage_reason": " + ".join(blockers) if blockers else "operator entry expansion is blocked",
            "next_step_hint": "resolve approval blocker and execution review before reopening entries",
            "sample_progress_hint": "lineage sample collection is not sufficient for a selected trial yet",
        }
    if stage == "1_SAMPLE_COLLECTION":
        return {
            "stage_reason": "eligible closed trades exist but no trial runs have been written",
            "next_step_hint": "continue paper lineage collection during active sessions",
            "sample_progress_hint": "waiting for trial_runs_written > 0 to start lineage selection",
        }
    if stage == "2_LINEAGE_READY":
        return {
            "stage_reason": (
                "selected trial is available"
                if selected_trial_run_id is not None
                else "trial runs have started and lineage selection can progress"
            ),
            "next_step_hint": "review validation and checklist surfaces for approval progression",
            "sample_progress_hint": (
                f"eligible_closed_trades={eligible_closed_trades}, trial_runs_written={trial_runs_written}"
            ),
        }
    if stage == "3_APPROVAL_REVIEW":
        return {
            "stage_reason": "lineage is ready enough for approval review but rollout still needs operator confirmation",
            "next_step_hint": "review validation and checklist before changing any runtime state",
            "sample_progress_hint": (
                f"eligible_closed_trades={eligible_closed_trades}, trial_runs_written={trial_runs_written}"
            ),
        }
    return {
        "stage_reason": "stage needs manual interpretation from validation, checklist, and dashboard surfaces",
        "next_step_hint": "review server-side operator surfaces directly",
        "sample_progress_hint": (
            f"eligible_closed_trades={eligible_closed_trades}, trial_runs_written={trial_runs_written}"
        ),
    }


def _build_stage_payload(
    validation_report: dict[str, Any],
    checklist: dict[str, Any],
    dashboard: dict[str, Any],
    *,
    symbol: str = "BTCUSDC",
    universe: str = "usdc_perp_top30",
    days: int = 30,
) -> dict[str, Any]:
    deployment = validation_report.get("deployment_approval_summary") or {}
    trial_writer_summary = validation_report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {}
    sample_counts = trial_writer_summary.get("sample_counts") or {}
    execution_advisory = validation_report.get("execution_degradation_advisory_summary") or {}
    operator_action_priority = validation_report.get("operator_action_priority_summary") or {}
    alpha_research_pipeline = validation_report.get("alpha_research_pipeline_summary") or {}
    validation_strip = _surface_strip_summary(validation_report, surface_type="validation")
    checklist_strip = _surface_strip_summary(checklist, surface_type="checklist")
    dashboard_strip = _surface_strip_summary(dashboard, surface_type="dashboard")
    edge_experiment_review = _edge_experiment_summary(validation_report, dashboard)
    edge_evolution_rule = _edge_evolution_summary(validation_report, dashboard)
    review_followup_ledger = _review_followup_summary(validation_report, dashboard)
    representative_candidates = _representative_candidates(dashboard)
    entry_timing_review_target = _experiment_review_target(
        operator_action_priority,
        target_key="entry_timing_target",
        preferred_key="entry_timing_preferred_variant",
        action="run_entry_timing_split_review",
        universe=universe,
        days=days,
    )
    execution_style_review_target = _experiment_review_target(
        operator_action_priority,
        target_key="execution_style_target",
        preferred_key="execution_style_preferred_variant",
        action="run_execution_style_split_review",
        universe=universe,
        days=days,
    )

    stage = _stage_from_payload(validation_report, checklist, dashboard)
    payload = {
        "stage": stage,
        "close_only_active": _active_close_only(dashboard),
        "playbook_go_no_go": deployment.get("playbook_go_no_go"),
        "deployment_go_no_go": deployment.get("deployment_go_no_go"),
        "checklist_status": checklist.get("overall_status"),
        "eligible_closed_trades": sample_counts.get("eligible_closed_trades"),
        "trial_runs_written": sample_counts.get("trial_runs_written"),
        "selected_trial_run_id": trial_writer_summary.get("selected_trial_run_id"),
        "execution_degradation": execution_advisory.get("status"),
        "top_operator_action": operator_action_priority.get("top_action"),
        "top_operator_action_followup_command": operator_action_priority.get("top_action_followup_command") or "",
        "dashboard_approval_strip": dashboard_strip,
        "validation_approval_strip": validation_strip,
        "checklist_approval_strip": checklist_strip,
        "edge_experiment_review": edge_experiment_review,
        "edge_evolution_rule": edge_evolution_rule,
        "review_followup_ledger": review_followup_ledger,
        "entry_timing_review_target": entry_timing_review_target,
        "execution_style_review_target": execution_style_review_target,
        "representative_candidates": representative_candidates,
        "alpha_research_next_step": (
            alpha_research_pipeline.get("recommended_action")
            or alpha_research_pipeline.get("softening_top_bucket")
            or alpha_research_pipeline.get("promotion_top_bucket")
        ),
    }
    payload["readiness_gates"] = _readiness_gates(
        selected_trial_run_id=trial_writer_summary.get("selected_trial_run_id"),
        trial_runs_written=sample_counts.get("trial_runs_written"),
        representative_candidates=representative_candidates,
        entry_timing_review_target=entry_timing_review_target,
        execution_style_review_target=execution_style_review_target,
        edge_experiment_review=edge_experiment_review,
    )
    payload["lineage_gate_ready"] = bool(payload["readiness_gates"]["lineage_gate_ready"])
    payload["candidate_gate_ready"] = bool(payload["readiness_gates"]["candidate_gate_ready"])
    payload["edge_sample_gate_ready"] = bool(payload["readiness_gates"]["edge_sample_gate_ready"])
    payload["all_readiness_gates_ready"] = bool(payload["readiness_gates"]["all_ready"])
    payload.update(_stage_message_fields(stage, validation_report, checklist, dashboard))
    return payload


def _print_human(payload: dict[str, Any]) -> None:
    print(f"stage: {payload['stage']}")
    print(f"stage_reason: {payload['stage_reason']}")
    print(f"next_step_hint: {payload['next_step_hint']}")
    print(f"sample_progress_hint: {payload['sample_progress_hint']}")
    print(f"close_only_active: {payload['close_only_active']}")
    print(_surface_summary_line("dashboard_surface", payload.get("dashboard_approval_strip") or {}))
    print(_surface_summary_line("validation_surface", payload.get("validation_approval_strip") or {}))
    print(_surface_summary_line("checklist_surface", payload.get("checklist_approval_strip") or {}))
    print(_edge_experiment_summary_line(payload.get("edge_experiment_review")))
    print(_edge_evolution_summary_line(payload.get("edge_evolution_rule")))
    print(_review_followup_summary_line(payload.get("review_followup_ledger")))
    print(_experiment_review_target_line("entry_timing_review_target", payload.get("entry_timing_review_target")))
    print(_experiment_review_target_line("execution_style_review_target", payload.get("execution_style_review_target")))
    representative_candidates = payload.get("representative_candidates") or {}
    print(_representative_candidate_summary_line("accepted_candidate_focus", representative_candidates.get("accepted")))
    print(_representative_candidate_summary_line("blocked_candidate_focus", representative_candidates.get("blocked")))
    print(f"readiness_gates: {(payload.get('readiness_gates') or {}).get('summary', 'unavailable')}")
    print(f"checklist_status: {payload['checklist_status']}")
    print(f"eligible_closed_trades: {payload['eligible_closed_trades']}")
    print(f"trial_runs_written: {payload['trial_runs_written']}")
    print(f"selected_trial_run_id: {payload['selected_trial_run_id']}")
    print(f"execution_degradation: {payload['execution_degradation']}")
    print(f"top_operator_action: {payload['top_operator_action']}")
    print(f"top_operator_action_followup_command: {payload.get('top_operator_action_followup_command') or 'none'}")
    print(f"alpha_research_next_step: {payload['alpha_research_next_step']}")


def main() -> int:
    args = parse_args()
    validation = _request_json(
        args.base_url,
        "POST",
        "/validation/report",
        query={"symbol": args.symbol},
    )
    checklist = _request_json(
        args.base_url,
        "POST",
        "/operations/checklist",
        query={
            "symbol": args.symbol,
            "universe": args.universe,
            "limit": max(1, args.limit),
            "days": max(1, args.days),
            "alert_test_lookback_hours": max(1, args.alert_test_lookback_hours),
        },
    )
    dashboard = _request_json(
        args.base_url,
        "GET",
        "/execution/operator-dashboard",
        query={
            "symbol": args.symbol,
            "universe": args.universe,
            "portfolio_limit": max(1, args.limit),
            "intent_limit": max(1, args.limit),
            "reconcile_limit": max(1, args.limit),
            "days": max(1, args.days),
        },
    )

    validation_report = validation.get("validation_report") or validation
    payload = _build_stage_payload(
        validation_report,
        checklist,
        dashboard,
        symbol=args.symbol,
        universe=args.universe,
        days=args.days,
    )
    if not args.no_write_stage:
        _write_stage_file(Path(args.stage_file).resolve(), payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(payload)
        print("")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
