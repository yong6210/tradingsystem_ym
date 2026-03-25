#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.notification_dispatcher import NotificationDispatcher


ACTIONABLE_ENTRY = "ACTIONABLE_ENTRY"
BLOCKED_SETUP = "BLOCKED_SETUP"
RESEARCH_ONLY_SETUP = "RESEARCH_ONLY_SETUP"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read the live portfolio budget surface and send a Discord message for actionable, blocked, "
            "or research-only entry setups."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--symbol", default="")
    parser.add_argument("--max-per-status", type=int, default=3)
    parser.add_argument("--channel", choices=["discord", "system"], default="discord")
    parser.add_argument(
        "--state-file",
        default=str(ROOT_DIR / "reports/operations/entry_surface/last_alert_state.json"),
    )
    parser.add_argument("--webhook-url", default="")
    parser.add_argument("--force-send", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"state file is not valid json: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"state file is invalid: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method.upper()} {path} failed: {exc.reason}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"{method.upper()} {path} returned a non-object payload")
    return payload


def _candidate_family(row: dict[str, Any]) -> str:
    direct = str(row.get("strategy_family") or "").strip()
    if direct:
        return direct
    thesis = row.get("thesis_fingerprint")
    if isinstance(thesis, dict):
        family = str(thesis.get("strategy_family") or "").strip()
        if family:
            return family
    return "unknown_family"


def _candidate_scope(payload: dict[str, Any], symbol: str) -> str:
    if symbol:
        return symbol.upper()
    return str(payload.get("universe") or "unknown_scope").upper()


def _matches_symbol(row: dict[str, Any], symbol: str) -> bool:
    if not symbol:
        return True
    return str(row.get("symbol") or "").upper() == symbol.upper()


def _filter_rows(rows: Any, *, symbol: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict) and _matches_symbol(row, symbol)]


def _blocked_topline_reason(payload: dict[str, Any]) -> tuple[str, str]:
    deployment_state = str(payload.get("deployment_go_no_go") or "MANUAL_REVIEW").upper()
    message = str(payload.get("deployment_message") or "Runtime gate requires manual review.").strip()
    if deployment_state == "NO_GO":
        return ("runtime_topline_no_go", message)
    return ("runtime_topline_manual_review", message)


def _approval_strip_summary(payload: dict[str, Any]) -> dict[str, str]:
    summary = dict(payload.get("approval_strip_summary") or {})
    if summary:
        return {
            "primary_reason": str(summary.get("primary_reason") or ""),
            "approve_value": str(summary.get("approve_value") or "n/a"),
            "approve_reason": str(summary.get("approve_reason") or ""),
            "align_value": str(summary.get("align_value") or "n/a"),
            "align_reason": str(summary.get("align_reason") or ""),
            "act_value": str(summary.get("act_value") or "continue_runtime_monitoring"),
            "act_reason": str(summary.get("act_reason") or ""),
            "act_priority_level": str(summary.get("act_priority_level") or "monitor"),
        }

    deployment_state = str(payload.get("deployment_go_no_go") or "MANUAL_REVIEW").upper()
    playbook_state = str(payload.get("playbook_go_no_go") or deployment_state).upper()
    deployment_message = str(payload.get("deployment_message") or "").strip()
    playbook_message = str(payload.get("playbook_message") or "").strip()
    approve_value = "approval usable"
    if deployment_state == "NO_GO":
        approve_value = "runtime no_go"
    elif deployment_state == "MANUAL_REVIEW":
        approve_value = "manual review first"
    align_value = "aligned" if deployment_state == playbook_state else "playbook_drift"
    priority_map = {"NO_GO": "urgent", "MANUAL_REVIEW": "watch", "GO": "monitor"}
    return {
        "primary_reason": deployment_message or playbook_message,
        "approve_value": approve_value,
        "approve_reason": deployment_message or playbook_message,
        "align_value": align_value,
        "align_reason": deployment_message or playbook_message,
        "act_value": str(payload.get("playbook_action") or "review_portfolio_runtime_state"),
        "act_reason": playbook_message or deployment_message,
        "act_priority_level": priority_map.get(deployment_state, "monitor"),
    }


def _edge_experiment_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    summary = dict(payload.get("edge_experiment_review") or {})
    if not summary:
        return None
    edge_proof_posture = dict(summary.get("edge_proof_posture") or {})
    daily_edge_kpis = dict(summary.get("daily_edge_kpis") or {})
    return {
        "available": bool(summary.get("available", True)),
        "advisory_only": bool(summary.get("advisory_only", True)),
        "edge_state": str(summary.get("edge_state") or "insufficient_edge_measurement"),
        "true_edge_ratio": float(summary.get("true_edge_ratio", 0.0) or 0.0),
        "edge_decay_rate": float(summary.get("edge_decay_rate", 0.0) or 0.0),
        "entry_timing_preferred_variant": str(summary.get("entry_timing_preferred_variant") or "none"),
        "execution_style_preferred_variant": str(summary.get("execution_style_preferred_variant") or "none"),
        "focus_symbol": str(summary.get("focus_symbol") or ""),
        "focus_status": str(summary.get("focus_status") or ""),
        "edge_proof_goal_closed_trades": int(
            summary.get("edge_proof_goal_closed_trades") or edge_proof_posture.get("edge_proof_goal_closed_trades") or 0
        ),
        "remaining_closed_trades_to_edge_proof_goal": int(
            summary.get("remaining_closed_trades_to_edge_proof_goal")
            or edge_proof_posture.get("remaining_closed_trades_to_edge_proof_goal")
            or 0
        ),
        "edge_proof_posture": {
            "state": str(edge_proof_posture.get("state") or "unknown"),
            "claim_state": str(edge_proof_posture.get("claim_state") or "unknown"),
        },
        "daily_edge_kpis": {
            "closed_trade_count": int(daily_edge_kpis.get("closed_trade_count", summary.get("closed_trade_count", 0)) or 0),
            "sample_maturity_state": str(
                daily_edge_kpis.get("sample_maturity_state") or summary.get("sample_maturity_state") or "unknown"
            ),
            "true_edge_ratio": float(daily_edge_kpis.get("true_edge_ratio", summary.get("true_edge_ratio", 0.0)) or 0.0),
            "edge_decay_rate": float(daily_edge_kpis.get("edge_decay_rate", summary.get("edge_decay_rate", 0.0)) or 0.0),
            "regime_dependency_state": str(
                daily_edge_kpis.get("regime_dependency_state") or summary.get("regime_dependency_state") or "not_available"
            ),
        },
        "summary": str(summary.get("summary") or ""),
    }


def _edge_evolution_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    summary = dict(payload.get("edge_evolution_rule") or {})
    if not summary:
        return None
    return {
        "available": bool(summary.get("available", True)),
        "advisory_only": bool(summary.get("advisory_only", True)),
        "evolution_state": str(summary.get("evolution_state") or "insufficient_sample"),
        "recommended_action": str(summary.get("recommended_action") or "keep_current_baseline"),
        "allocation_bias": str(summary.get("allocation_bias") or "hold_current_baseline"),
        "promotion_candidate_axis": str(summary.get("promotion_candidate_axis") or "none"),
        "promotion_candidate_variant": str(summary.get("promotion_candidate_variant") or "none"),
        "summary": str(summary.get("summary") or ""),
    }


def _review_followup_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    summary = dict(payload.get("review_followup_ledger") or {})
    if not summary:
        return None
    return {
        "available": bool(summary.get("available", False)),
        "last_status": str(summary.get("last_status") or "none"),
        "last_generated_status": str(summary.get("last_generated_status") or summary.get("last_status") or "none"),
        "last_decision_status": str(summary.get("last_decision_status") or "none"),
        "last_effective_status": str(summary.get("last_effective_status") or summary.get("last_status") or "none"),
        "last_action": str(summary.get("last_action") or "none"),
        "recent_entry_count": int(summary.get("recent_entry_count", 0) or 0),
        "last_followup_command": str(summary.get("last_followup_command") or ""),
        "summary": str(summary.get("summary") or ""),
    }


def _sort_actionable_key(row: dict[str, Any]) -> tuple[float, float, float, str]:
    return (
        float(row.get("adjusted_rank_score", row.get("final_rank_score", 0.0)) or 0.0),
        float(row.get("expected_ev_at_recommended_size_r", row.get("expected_ev_r", 0.0)) or 0.0),
        float(row.get("recommended_risk_r", 0.0) or 0.0),
        str(row.get("symbol") or ""),
    )


def _sort_blocked_key(row: dict[str, Any]) -> tuple[float, float, str]:
    return (
        float(row.get("base_rank_score", row.get("final_rank_score", 0.0)) or 0.0),
        float(row.get("expected_ev_at_recommended_size_r", row.get("expected_ev_r", 0.0)) or 0.0),
        str(row.get("symbol") or ""),
    )


def _sort_research_key(row: dict[str, Any]) -> tuple[float, float, float, str]:
    return (
        float(row.get("expected_ev_at_recommended_size_r", row.get("expected_ev_r", 0.0)) or 0.0),
        float(row.get("alpha_research_softened_risk_r", 0.0) or 0.0),
        -float(row.get("alpha_research_gap", 0.0) or 0.0),
        str(row.get("symbol") or ""),
    )


def build_entry_snapshot(
    payload: dict[str, Any],
    *,
    symbol: str = "",
    max_per_status: int = 3,
) -> dict[str, Any]:
    accepted_rows = _filter_rows(payload.get("accepted_candidates"), symbol=symbol)
    blocked_rows = _filter_rows(payload.get("blocked_candidates"), symbol=symbol)
    research_rows = _filter_rows(payload.get("alpha_research_candidates"), symbol=symbol)

    research_plan_ids = {str(row.get("plan_id") or "") for row in research_rows}
    blocked_non_research = [row for row in blocked_rows if str(row.get("plan_id") or "") not in research_plan_ids]

    deployment_state = str(payload.get("deployment_go_no_go") or "MANUAL_REVIEW").upper()
    actionable_rows: list[dict[str, Any]] = []
    if deployment_state == "GO":
        actionable_rows = accepted_rows
    else:
        reason_code, reason_message = _blocked_topline_reason(payload)
        for row in accepted_rows:
            shadow = dict(row)
            shadow["block_reason"] = shadow.get("block_reason") or reason_code
            shadow["block_reason_message"] = shadow.get("block_reason_message") or reason_message
            blocked_non_research.append(shadow)

    actionable_rows = sorted(actionable_rows, key=_sort_actionable_key, reverse=True)[: max(0, int(max_per_status))]
    blocked_non_research = sorted(blocked_non_research, key=_sort_blocked_key, reverse=True)[: max(0, int(max_per_status))]
    research_rows = sorted(research_rows, key=_sort_research_key, reverse=True)[: max(0, int(max_per_status))]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": _candidate_scope(payload, symbol),
        "deployment_go_no_go": deployment_state,
        "deployment_code": str(payload.get("deployment_code") or ""),
        "deployment_message": str(payload.get("deployment_message") or ""),
        "playbook_go_no_go": str(payload.get("playbook_go_no_go") or ""),
        "playbook_action": str(payload.get("playbook_action") or ""),
        "approval_strip": _approval_strip_summary(payload),
        "edge_experiment_review": _edge_experiment_summary(payload),
        "edge_evolution_rule": _edge_evolution_summary(payload),
        "review_followup_ledger": _review_followup_summary(payload),
        "counts": {
            ACTIONABLE_ENTRY: len(actionable_rows),
            BLOCKED_SETUP: len(blocked_non_research),
            RESEARCH_ONLY_SETUP: len(research_rows),
        },
        "sections": {
            ACTIONABLE_ENTRY: actionable_rows,
            BLOCKED_SETUP: blocked_non_research,
            RESEARCH_ONLY_SETUP: research_rows,
        },
    }


def build_alert_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    sections = dict(snapshot.get("sections") or {})
    approval_strip = dict(snapshot.get("approval_strip") or {})
    edge_experiment = dict(snapshot.get("edge_experiment_review") or {})
    edge_evolution = dict(snapshot.get("edge_evolution_rule") or {})
    review_followup = dict(snapshot.get("review_followup_ledger") or {})
    return {
        "scope": str(snapshot.get("scope") or ""),
        "deployment_go_no_go": str(snapshot.get("deployment_go_no_go") or ""),
        "deployment_code": str(snapshot.get("deployment_code") or ""),
        "playbook_go_no_go": str(snapshot.get("playbook_go_no_go") or ""),
        "playbook_action": str(snapshot.get("playbook_action") or ""),
        "approval_strip_approve": str(approval_strip.get("approve_value") or ""),
        "approval_strip_align": str(approval_strip.get("align_value") or ""),
        "approval_strip_act": str(approval_strip.get("act_value") or ""),
        "approval_strip_priority": str(approval_strip.get("act_priority_level") or ""),
        "edge_state": str(edge_experiment.get("edge_state") or ""),
        "edge_proof_state": str(dict(edge_experiment.get("edge_proof_posture") or {}).get("state") or ""),
        "edge_claim_state": str(dict(edge_experiment.get("edge_proof_posture") or {}).get("claim_state") or ""),
        "edge_proof_remaining": int(edge_experiment.get("remaining_closed_trades_to_edge_proof_goal", 0) or 0),
        "edge_regime_dependency_state": str(
            dict(edge_experiment.get("daily_edge_kpis") or {}).get("regime_dependency_state") or ""
        ),
        "edge_evolution_state": str(edge_evolution.get("evolution_state") or ""),
        "edge_evolution_action": str(edge_evolution.get("recommended_action") or ""),
        "edge_evolution_bias": str(edge_evolution.get("allocation_bias") or ""),
        "entry_timing_focus": str(edge_experiment.get("entry_timing_preferred_variant") or ""),
        "execution_style_focus": str(edge_experiment.get("execution_style_preferred_variant") or ""),
        "review_followup_generated_status": str(review_followup.get("last_status") or ""),
        "review_followup_decision_status": str(review_followup.get("last_decision_status") or ""),
        "review_followup_effective_status": str(review_followup.get("last_effective_status") or ""),
        "review_followup_action": str(review_followup.get("last_action") or ""),
        "review_followup_entries": int(review_followup.get("recent_entry_count", 0) or 0),
        "review_followup_command": str(review_followup.get("last_followup_command") or ""),
        "counts": {
            ACTIONABLE_ENTRY: int((snapshot.get("counts") or {}).get(ACTIONABLE_ENTRY, 0) or 0),
            BLOCKED_SETUP: int((snapshot.get("counts") or {}).get(BLOCKED_SETUP, 0) or 0),
            RESEARCH_ONLY_SETUP: int((snapshot.get("counts") or {}).get(RESEARCH_ONLY_SETUP, 0) or 0),
        },
        "sections": {
            ACTIONABLE_ENTRY: [_row_alert_identity(ACTIONABLE_ENTRY, row) for row in sections.get(ACTIONABLE_ENTRY) or []],
            BLOCKED_SETUP: [_row_alert_identity(BLOCKED_SETUP, row) for row in sections.get(BLOCKED_SETUP) or []],
            RESEARCH_ONLY_SETUP: [
                _row_alert_identity(RESEARCH_ONLY_SETUP, row) for row in sections.get(RESEARCH_ONLY_SETUP) or []
            ],
        },
    }


def _row_alert_identity(status: str, row: dict[str, Any]) -> dict[str, Any]:
    edge_focus = dict(row.get("edge_experiment_focus") or {})
    payload = {
        "symbol": str(row.get("symbol") or ""),
        "plan_id": str(row.get("plan_id") or ""),
        "direction": str(row.get("direction") or "").lower(),
        "entry_model": str(row.get("entry_model") or "").upper(),
        "family": _candidate_family(row),
        "edge_state": str(edge_focus.get("edge_state") or ""),
        "entry_timing_focus": str(edge_focus.get("entry_timing_preferred_variant") or ""),
        "execution_style_focus": str(edge_focus.get("execution_style_preferred_variant") or ""),
    }
    if status == BLOCKED_SETUP:
        payload["reason_code"] = str(row.get("block_reason") or "")
    elif status == RESEARCH_ONLY_SETUP:
        payload["reason_code"] = str(row.get("alpha_research_reason") or row.get("block_reason") or "")
    return payload


def _extract_alert_state(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    nested = payload.get("alert_state")
    if isinstance(nested, dict):
        return nested
    return payload


def _format_candidate_line(status: str, row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "UNKNOWN")
    direction = str(row.get("direction") or "").lower() or "unknown"
    entry_model = str(row.get("entry_model") or "").upper() or "UNKNOWN"
    family = _candidate_family(row)
    risk_r = float(row.get("recommended_risk_r", 0.0) or 0.0)
    expected_summary = str(row.get("expected_summary") or "").strip()

    parts = [f"{symbol} {direction} {entry_model}", f"family={family}", f"risk={risk_r:.2f}R"]
    if expected_summary:
        parts.append(expected_summary)

    edge_focus = dict(row.get("edge_experiment_focus") or {})
    if edge_focus:
        parts.append(f"edge={edge_focus.get('edge_state', 'insufficient_edge_measurement')}")
        parts.append(
            "split="
            f"{edge_focus.get('entry_timing_preferred_variant', 'none')}"
            f"/{edge_focus.get('execution_style_preferred_variant', 'none')}"
        )

    if status == BLOCKED_SETUP:
        message = str(row.get("block_reason_message") or row.get("block_reason") or "blocked").strip()
        parts.append(f"reason={message}")
    elif status == RESEARCH_ONLY_SETUP:
        message = str(
            row.get("alpha_research_reason_message")
            or row.get("alpha_research_reason")
            or row.get("block_reason_message")
            or "research-only"
        ).strip()
        softened_risk = float(row.get("alpha_research_softened_risk_r", 0.0) or 0.0)
        parts.append(f"reason={message}")
        parts.append(f"softened_risk={softened_risk:.2f}R")
    else:
        adjusted_rank = float(row.get("adjusted_rank_score", row.get("final_rank_score", 0.0)) or 0.0)
        parts.append(f"rank={adjusted_rank:.2f}")

    return "- " + " | ".join(parts)


def _format_contract_trace(snapshot: dict[str, Any]) -> str:
    approval_strip = dict(snapshot.get("approval_strip") or {})
    return (
        f"contract_trace: approve={approval_strip.get('approve_value')} "
        f"| align={approval_strip.get('align_value')} "
        f"| act={approval_strip.get('act_value')} "
        f"| runtime={snapshot.get('deployment_go_no_go')}/{snapshot.get('deployment_code')} "
        f"| playbook={snapshot.get('playbook_go_no_go')}"
    )


def _format_edge_experiment_trace(snapshot: dict[str, Any]) -> str:
    edge_experiment = dict(snapshot.get("edge_experiment_review") or {})
    if not edge_experiment:
        return "edge_experiment: unavailable"
    focus = str(edge_experiment.get("focus_symbol") or "")
    focus_status = str(edge_experiment.get("focus_status") or "")
    focus_suffix = f" | focus={focus}/{focus_status}" if focus and focus_status else ""
    posture = dict(edge_experiment.get("edge_proof_posture") or {})
    kpis = dict(edge_experiment.get("daily_edge_kpis") or {})
    return (
        f"edge_experiment: state={edge_experiment.get('edge_state')} "
        f"| entry_timing={edge_experiment.get('entry_timing_preferred_variant')} "
        f"| execution_style={edge_experiment.get('execution_style_preferred_variant')} "
        f"| proof={posture.get('state', 'unknown')}/{posture.get('claim_state', 'unknown')} "
        f"| closes={int(kpis.get('closed_trade_count', 0) or 0)}/{int(edge_experiment.get('edge_proof_goal_closed_trades', 0) or 0)} "
        f"| remaining={int(edge_experiment.get('remaining_closed_trades_to_edge_proof_goal', 0) or 0)} "
        f"| regime={kpis.get('regime_dependency_state', 'not_available')} "
        f"| true_edge={float(kpis.get('true_edge_ratio', edge_experiment.get('true_edge_ratio', 0.0)) or 0.0):.4f} "
        f"| decay={float(kpis.get('edge_decay_rate', edge_experiment.get('edge_decay_rate', 0.0)) or 0.0):.4f}"
        f"{focus_suffix}"
    )


def _format_edge_evolution_trace(snapshot: dict[str, Any]) -> str:
    edge_evolution = dict(snapshot.get("edge_evolution_rule") or {})
    if not edge_evolution:
        return "edge_evolution: unavailable"
    return (
        f"edge_evolution: state={edge_evolution.get('evolution_state')} "
        f"| action={edge_evolution.get('recommended_action')} "
        f"| bias={edge_evolution.get('allocation_bias')} "
        f"| promotion={edge_evolution.get('promotion_candidate_axis')}/{edge_evolution.get('promotion_candidate_variant')}"
    )


def _format_review_followup_trace(snapshot: dict[str, Any]) -> str:
    review_followup = dict(snapshot.get("review_followup_ledger") or {})
    if not review_followup:
        return "review_followup_ledger: unavailable"
    return (
        f"review_followup_ledger: generated={review_followup.get('last_status', 'none')} "
        f"| decision={review_followup.get('last_decision_status', 'none')} "
        f"| effective={review_followup.get('last_effective_status', 'none')} "
        f"| action={review_followup.get('last_action', 'none')} "
        f"| entries={int(review_followup.get('recent_entry_count', 0) or 0)} "
        f"| cmd={review_followup.get('last_followup_command', '') or 'none'}"
    )


def render_message(snapshot: dict[str, Any]) -> str:
    counts = dict(snapshot.get("counts") or {})
    sections = dict(snapshot.get("sections") or {})
    approval_strip = dict(snapshot.get("approval_strip") or {})
    lines = [
        "Trading entry surface alert",
        f"scope: {snapshot.get('scope')}",
        (
            f"approval_strip: approve={approval_strip.get('approve_value')} "
            f"| align={approval_strip.get('align_value')} "
            f"| act={approval_strip.get('act_value')} "
            f"| priority={approval_strip.get('act_priority_level')}"
        ),
        f"reason: {approval_strip.get('primary_reason') or snapshot.get('deployment_message')}",
        _format_contract_trace(snapshot),
        _format_edge_experiment_trace(snapshot),
        _format_edge_evolution_trace(snapshot),
        _format_review_followup_trace(snapshot),
        (
            f"counts: {ACTIONABLE_ENTRY}={counts.get(ACTIONABLE_ENTRY, 0)}, "
            f"{BLOCKED_SETUP}={counts.get(BLOCKED_SETUP, 0)}, "
            f"{RESEARCH_ONLY_SETUP}={counts.get(RESEARCH_ONLY_SETUP, 0)}"
        ),
    ]

    for status in (ACTIONABLE_ENTRY, BLOCKED_SETUP, RESEARCH_ONLY_SETUP):
        rows = sections.get(status) or []
        lines.append("")
        lines.append(f"{status}")
        if not rows:
            lines.append("- none")
            continue
        lines.extend(_format_candidate_line(status, row) for row in rows)
    return "\n".join(lines)


def _has_alertable_rows(snapshot: dict[str, Any]) -> bool:
    counts = dict(snapshot.get("counts") or {})
    return any(int(counts.get(status, 0) or 0) > 0 for status in (ACTIONABLE_ENTRY, BLOCKED_SETUP, RESEARCH_ONLY_SETUP))


def main() -> int:
    args = parse_args()
    state_file = Path(args.state_file).resolve()
    payload = _request_json(
        args.base_url,
        "GET",
        "/portfolio/budget",
        query={
            "universe": args.universe,
            "limit": args.limit,
            "write_report": "false",
        },
    )
    snapshot = build_entry_snapshot(
        payload,
        symbol=str(args.symbol or "").strip(),
        max_per_status=max(0, int(args.max_per_status)),
    )
    alert_state = build_alert_state(snapshot)
    state_warning = ""
    try:
        previous_payload = _read_json(state_file)
    except RuntimeError as exc:
        previous_payload = None
        state_warning = str(exc)
    previous_state = _extract_alert_state(previous_payload)

    result: dict[str, Any] = {
        "base_url": args.base_url,
        "universe": args.universe,
        "symbol": str(args.symbol or "").strip() or None,
        "channel": args.channel,
        "state_file": str(state_file),
        "dry_run": bool(args.dry_run),
        "force_send": bool(args.force_send),
        "snapshot": snapshot,
        "alert_state": alert_state,
        "notified": False,
        "state_written": False,
        "dedupe_suppressed": False,
    }
    if state_warning:
        result["state_warning"] = state_warning

    if not _has_alertable_rows(snapshot):
        result["reason"] = "no_alertable_rows"
        if not args.dry_run:
            _write_json(
                state_file,
                {
                    "updated_at": datetime.now(UTC).isoformat(),
                    "alert_state": alert_state,
                    "reason": "no_alertable_rows",
                },
            )
            result["state_written"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if previous_state == alert_state and not args.force_send:
        result["reason"] = "unchanged_surface_state"
        result["dedupe_suppressed"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    message = render_message(snapshot)
    result["message"] = message

    if args.dry_run:
        result["reason"] = "dry_run"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    settings = get_settings()
    if args.webhook_url.strip():
        settings.alert_discord_webhook_url = args.webhook_url.strip()

    dispatcher = NotificationDispatcher(settings)
    delivery = dispatcher.dispatch(
        channel=args.channel,
        alert_type="entry_surface_alert",
        symbol=str(snapshot.get("scope") or args.universe).upper(),
        payload={"message": message},
    )
    result["notified"] = bool(delivery.get("delivered"))
    result["delivery"] = delivery
    if bool(delivery.get("delivered")):
        _write_json(
            state_file,
            {
                "updated_at": datetime.now(UTC).isoformat(),
                "alert_state": alert_state,
                "delivery": {
                    "channel": delivery.get("channel"),
                    "reason": delivery.get("reason"),
                    "target": delivery.get("target"),
                },
            },
        )
        result["state_written"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
