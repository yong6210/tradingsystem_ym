#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import func, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.models import OrderSubmission
from app.db.session import SessionLocal, init_db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review whether contract pruning should be reopened after a live cycle.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--report-dir", default="reports/operations/pruning_reviews")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url += f"?{urlencode(query, doseq=True)}"
    data: bytes | None = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url=url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {payload}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method.upper()} {path} failed: {exc.reason}") from exc


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


def _surface_allows_pruning_reopen(summary: dict[str, str]) -> bool:
    approve_value = str(summary.get("approve_value") or "").strip().lower()
    return approve_value not in {"runtime no_go", "validation no_go", "validation/checklist no_go", "entry gate blocked"}


def _surface_summary_line(label: str, summary: dict[str, str]) -> str:
    return (
        f"{label}: approve={summary.get('approve_value', 'n/a')} | "
        f"align={summary.get('align_value', 'n/a')} | "
        f"act={summary.get('act_value', 'continue_runtime_monitoring')}"
    )


def _edge_experiment_summary(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    dashboard_source = dict(
        (((dashboard_payload or {}).get("signal_funnel") or {}).get("edge_experiment_review") or {})
    )
    validation_source = dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("edge_experiment_review_summary") or {})
    )
    source = dashboard_source or validation_source
    if not source:
        return None

    source_summary = dict(source.get("source_summary") or {})
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
    }


def _edge_experiment_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "edge_experiment: unavailable"
    return (
        f"edge_experiment: state={summary.get('edge_state', 'insufficient_edge_measurement')} | "
        f"entry_timing={summary.get('entry_timing_preferred_variant', 'none')} | "
        f"execution_style={summary.get('execution_style_preferred_variant', 'none')} | "
        f"true_edge={float(summary.get('true_edge_ratio') or 0.0):.4f}"
    )


def _edge_evolution_summary(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    dashboard_source = dict(((((dashboard_payload or {}).get("signal_funnel") or {}).get("edge_evolution_rule")) or {}))
    validation_source = dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("edge_evolution_rule_summary") or {})
    )
    source = dashboard_source or validation_source
    if not source:
        return None
    return {
        "available": bool(source.get("available", True)),
        "advisory_only": bool(source.get("advisory_only", True)),
        "evolution_state": str(source.get("evolution_state") or "insufficient_sample"),
        "recommended_action": str(source.get("recommended_action") or "keep_current_baseline"),
        "allocation_bias": str(source.get("allocation_bias") or "hold_current_baseline"),
        "summary": str(source.get("summary") or ""),
        "kill_review_triggered": bool(source.get("kill_review_triggered", False)),
        "promotion_candidate_axis": str(source.get("promotion_candidate_axis") or "none"),
        "promotion_candidate_variant": str(source.get("promotion_candidate_variant") or "none"),
    }


def _edge_evolution_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "edge_evolution: unavailable"
    return (
        f"edge_evolution: state={summary.get('evolution_state', 'insufficient_sample')} | "
        f"action={summary.get('recommended_action', 'keep_current_baseline')} | "
        f"bias={summary.get('allocation_bias', 'hold_current_baseline')} | "
        f"promotion={summary.get('promotion_candidate_axis', 'none')}/{summary.get('promotion_candidate_variant', 'none')}"
    )


def _review_followup_summary(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    dashboard_source = dict(((((dashboard_payload or {}).get("signal_funnel") or {}).get("review_followup_ledger")) or {}))
    validation_source = dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("review_followup_ledger_summary") or {})
    )
    source = dashboard_source or validation_source
    if not source:
        return None
    return {
        "available": bool(source.get("available", False)),
        "last_status": str(source.get("last_status") or "none"),
        "last_generated_status": str(source.get("last_generated_status") or source.get("last_status") or "none"),
        "last_decision_status": str(source.get("last_decision_status") or "none"),
        "last_effective_status": str(source.get("last_effective_status") or source.get("last_status") or "none"),
        "last_action": str(source.get("last_action") or "none"),
        "recent_entry_count": int(source.get("recent_entry_count", 0) or 0),
        "last_followup_command": str(source.get("last_followup_command") or ""),
        "summary": str(source.get("summary") or ""),
    }


def _review_followup_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "review_followup_ledger: unavailable"
    return (
        f"review_followup_ledger: generated={summary.get('last_status', 'none')} | "
        f"decision={summary.get('last_decision_status', 'none')} | "
        f"effective={summary.get('last_effective_status', 'none')} | "
        f"action={summary.get('last_action', 'none')} | "
        f"entries={int(summary.get('recent_entry_count', 0) or 0)} | "
        f"cmd={summary.get('last_followup_command', '') or 'none'}"
    )


def _edge_experiment_next_step(summary: dict[str, Any] | None) -> str | None:
    if not summary:
        return None
    edge_state = str(summary.get("edge_state") or "")
    entry_timing = str(summary.get("entry_timing_preferred_variant") or "none")
    execution_style = str(summary.get("execution_style_preferred_variant") or "none")
    if edge_state == "fragile_edge":
        return (
            "Advisory only: fragile post-cost edge; reopen pruning only after reviewing whether "
            f"entry_timing={entry_timing} and execution_style={execution_style} should stay in compare-only mode."
        )
    if edge_state == "watch_edge":
        return (
            "Advisory only: unstable post-cost edge; keep the pruning decision separate from the next split review "
            f"for entry_timing={entry_timing} and execution_style={execution_style}."
        )
    if edge_state == "insufficient_edge_measurement":
        return "Advisory only: edge evidence is still thin; do not treat pruning cleanup as edge validation."
    return None


def _edge_evolution_next_step(summary: dict[str, Any] | None) -> str | None:
    if not summary:
        return None
    evolution_state = str(summary.get("evolution_state") or "")
    action = str(summary.get("recommended_action") or "keep_current_baseline")
    axis = str(summary.get("promotion_candidate_axis") or "none")
    variant = str(summary.get("promotion_candidate_variant") or "none")
    if evolution_state == "edge_kill_review":
        return (
            "Advisory only: pruning cleanup is secondary while edge kill review is active; "
            f"run {action} before reopening scope."
        )
    if evolution_state == "reduce_candidate":
        return (
            "Advisory only: edge evolution still points to baseline reduction; keep pruning separate from "
            f"{action}."
        )
    if evolution_state == "promote_candidate":
        return (
            "Advisory only: preferred branch promotion review is now the higher-value follow-up; review "
            f"{axis}={variant} with {action} after pruning notes are captured."
        )
    return None


def _review_followup_next_step(summary: dict[str, Any] | None) -> str | None:
    if not summary:
        return None
    generated_status = str(summary.get("last_status") or "none")
    followup_command = str(summary.get("last_followup_command") or "").strip()
    if generated_status in {"NO_TARGET", "NO_REVIEW_ACTION_AVAILABLE"}:
        if followup_command:
            return (
                "Advisory only: the latest review packet stalled during generation at "
                f"`{generated_status}`; fix target contract carryover before rerunning `{followup_command}`."
            )
        return (
            "Advisory only: the latest review packet stalled during generation at "
            f"`{generated_status}`; fix target contract carryover before generating another packet."
        )
    return None


def _representative_candidates(dashboard_payload: dict[str, Any] | None) -> dict[str, Any]:
    portfolio = dict((dashboard_payload or {}).get("portfolio_summary") or {})

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


def _representative_candidate_line(label: str, candidate: dict[str, Any] | None) -> str:
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


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Post-Live Pruning Review")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- days: {payload['days']}")
    lines.append(f"- decision: {payload['decision']}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- rationale: {payload['rationale']}")
    lines.append(f"- live_submission_count: {payload['db_live_activity']['live_submission_count']}")
    lines.append(f"- live_binance_submission_count: {payload['db_live_activity']['live_binance_submission_count']}")
    lines.append(f"- live_fill_like_submission_count: {payload['db_live_activity']['filled_like_submission_count']}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for row in payload["checks"]:
        lines.append(f"- [{row['status']}] {row['name']}: {row['message']}")
    lines.append("")
    lines.append("## Approval Surfaces")
    lines.append("")
    for row in payload["approval_surfaces"]:
        lines.append(
            f"- {row['label']}: approve={row['approve_value']} | "
            f"align={row['align_value']} | act={row['act_value']} | "
            f"priority={row['act_priority_level']}"
        )
        lines.append(f"  reason={row['primary_reason'] or row['approve_reason'] or row['act_reason']}")
    lines.append("")
    lines.append("## Edge Experiment")
    lines.append("")
    edge_experiment = payload.get("edge_experiment_review") or {}
    if edge_experiment:
        lines.append(f"- {_edge_experiment_summary_line(edge_experiment)}")
        lines.append(f"- summary: {edge_experiment.get('summary', '')}")
    else:
        lines.append("- edge experiment unavailable")
    edge_evolution = payload.get("edge_evolution_rule") or {}
    if edge_evolution:
        lines.append(f"- {_edge_evolution_summary_line(edge_evolution)}")
        lines.append(f"- summary: {edge_evolution.get('summary', '')}")
    review_followup = payload.get("review_followup_ledger") or {}
    if review_followup:
        lines.append(f"- {_review_followup_summary_line(review_followup)}")
        lines.append(f"- summary: {review_followup.get('summary', '')}")
    representative_candidates = payload.get("representative_candidates") or {}
    lines.append(f"- {_representative_candidate_line('accepted_candidate_focus', representative_candidates.get('accepted'))}")
    lines.append(f"- {_representative_candidate_line('blocked_candidate_focus', representative_candidates.get('blocked'))}")
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
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    generated_at = _now()
    cutoff = generated_at - timedelta(days=max(args.days, 1))

    init_db()
    with SessionLocal() as db:
        live_submission_count = db.scalar(
            select(func.count())
            .select_from(OrderSubmission)
            .where(OrderSubmission.requested_live.is_(True), OrderSubmission.submitted_at >= cutoff)
        ) or 0
        live_binance_submission_count = db.scalar(
            select(func.count())
            .select_from(OrderSubmission)
            .where(
                OrderSubmission.requested_live.is_(True),
                OrderSubmission.adapter == "binance",
                OrderSubmission.submitted_at >= cutoff,
            )
        ) or 0
        filled_like_submission_count = db.scalar(
            select(func.count())
            .select_from(OrderSubmission)
            .where(
                OrderSubmission.requested_live.is_(True),
                OrderSubmission.state.in_(("FILLED", "PARTIALLY_FILLED")),
                OrderSubmission.submitted_at >= cutoff,
            )
        ) or 0

    dashboard = _request_json(
        args.base_url,
        "GET",
        "/execution/operator-dashboard",
        query={"symbol": args.symbol, "universe": args.universe, "days": args.days},
    )
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
        query={"symbol": args.symbol},
    )
    dashboard_strip = _surface_strip_summary(dashboard, surface_type="dashboard")
    validation_strip = _surface_strip_summary(validation, surface_type="validation")
    checklist_strip = _surface_strip_summary(checklist, surface_type="checklist")
    edge_experiment_review = _edge_experiment_summary(
        dashboard_payload=dashboard,
        validation_payload=validation,
    )
    edge_evolution_rule = _edge_evolution_summary(
        dashboard_payload=dashboard,
        validation_payload=validation,
    )
    review_followup_ledger = _review_followup_summary(
        dashboard_payload=dashboard,
        validation_payload=validation,
    )
    representative_candidates = _representative_candidates(dashboard)

    reconcile_summary = dashboard.get("recent_reconciliation_summary") or {}
    checks = [
        {
            "name": "actual_live_submissions_present",
            "status": "PASS" if live_submission_count > 0 else "FAIL",
            "message": f"live submissions in lookback={live_submission_count}",
        },
        {
            "name": "actual_binance_live_path_present",
            "status": "PASS" if live_binance_submission_count > 0 else "FAIL",
            "message": f"binance live submissions in lookback={live_binance_submission_count}",
        },
        {
            "name": "actual_live_fill_path_present",
            "status": "PASS" if filled_like_submission_count > 0 else "FAIL",
            "message": f"live filled/partial submissions in lookback={filled_like_submission_count}",
        },
        {
            "name": "reconciliation_recently_healthy",
            "status": "PASS" if bool(reconcile_summary.get("healthy", False)) else "FAIL",
            "message": f"healthy={reconcile_summary.get('healthy', False)} severity={reconcile_summary.get('highest_severity', 'UNKNOWN')}",
        },
        {
            "name": "validation_not_no_go",
            "status": "PASS" if _surface_allows_pruning_reopen(validation_strip) else "FAIL",
            "message": (
                f"approve={validation_strip.get('approve_value', '')} | "
                f"align={validation_strip.get('align_value', '')} | "
                f"act={validation_strip.get('act_value', '')} | "
                f"reason={validation_strip.get('approve_reason', '') or validation_strip.get('act_reason', '')}"
            ),
        },
        {
            "name": "checklist_not_no_go",
            "status": "PASS" if _surface_allows_pruning_reopen(checklist_strip) else "FAIL",
            "message": (
                f"approve={checklist_strip.get('approve_value', '')} | "
                f"align={checklist_strip.get('align_value', '')} | "
                f"act={checklist_strip.get('act_value', '')} | "
                f"reason={checklist_strip.get('approve_reason', '') or checklist_strip.get('act_reason', '')}"
            ),
        },
    ]

    should_reopen = (
        live_submission_count > 0
        and live_binance_submission_count > 0
        and filled_like_submission_count > 0
        and bool(reconcile_summary.get("healthy", False))
        and _surface_allows_pruning_reopen(validation_strip)
        and _surface_allows_pruning_reopen(checklist_strip)
    )
    decision = "REOPEN_PRUNING_REVIEW" if should_reopen else "KEEP_OPTIONAL_HOLD"
    rationale = (
        "At least one actual Binance live trading cycle exists, with fill-like activity and healthy reconciliation."
        if should_reopen
        else "No complete live operating cycle evidence yet; keep pruning review deferred."
    )
    next_steps = (
        [
            "Open the contract pruning review backlog and compare duplicated top-level vs nested execution/validation payloads.",
            "Audit operator-facing fields after the first live cycle before removing passthrough fields.",
        ]
        if should_reopen
        else [
            "Keep contract pruning on optional hold until at least one actual Binance live cycle completes.",
            "Rerun this review after a session with real requested_live=true Binance submissions and at least one fill-like outcome.",
        ]
    )
    advisory_next_step = _edge_experiment_next_step(edge_experiment_review)
    if advisory_next_step:
        next_steps.append(advisory_next_step)
    edge_evolution_next_step = _edge_evolution_next_step(edge_evolution_rule)
    if edge_evolution_next_step:
        next_steps.append(edge_evolution_next_step)
    review_followup_next_step = _review_followup_next_step(review_followup_ledger)
    if review_followup_next_step:
        next_steps.append(review_followup_next_step)

    payload = {
        "generated_at": generated_at.isoformat(),
        "symbol": args.symbol.upper(),
        "days": args.days,
        "decision": decision,
        "rationale": rationale,
        "checks": checks,
        "db_live_activity": {
            "cutoff": cutoff.isoformat(),
            "live_submission_count": int(live_submission_count),
            "live_binance_submission_count": int(live_binance_submission_count),
            "filled_like_submission_count": int(filled_like_submission_count),
        },
        "operator_dashboard_summary": {
            "execution_mode": dashboard.get("execution_mode", ""),
            "auto_trading_enabled": dashboard.get("auto_trading_enabled", False),
            "new_entries_allowed": dashboard.get("new_entries_allowed", False),
            "blocking_reason_code": dashboard.get("blocking_reason_code", ""),
            "blocking_reason_message": dashboard.get("blocking_reason_message", ""),
            "approval_strip_summary": dashboard_strip,
            "recent_reconciliation_summary": reconcile_summary,
        },
        "validation_summary": {
            "deployment_go_no_go": validation.get("deployment_go_no_go", ""),
            "deployment_code": validation.get("deployment_code", ""),
            "deployment_message": validation.get("deployment_message", ""),
            "playbook_go_no_go": validation.get("playbook_go_no_go", ""),
            "playbook_action": validation.get("playbook_action", ""),
            "approval_strip_summary": validation_strip,
        },
        "checklist_summary": {
            "deployment_go_no_go": checklist.get("deployment_go_no_go", ""),
            "deployment_code": checklist.get("deployment_code", ""),
            "deployment_message": checklist.get("deployment_message", ""),
            "playbook_go_no_go": checklist.get("playbook_go_no_go", ""),
            "playbook_action": checklist.get("playbook_action", ""),
            "approval_strip_summary": checklist_strip,
        },
        "approval_surfaces": [
            {"label": "dashboard", **dashboard_strip},
            {"label": "validation", **validation_strip},
            {"label": "checklist", **checklist_strip},
        ],
        "edge_experiment_review": edge_experiment_review,
        "edge_evolution_rule": edge_evolution_rule,
        "review_followup_ledger": review_followup_ledger,
        "representative_candidates": representative_candidates,
        "next_steps": next_steps,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"post_live_pruning_review_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
