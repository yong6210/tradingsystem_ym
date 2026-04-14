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
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    # Keep the documented `python scripts/...` entrypoint working without extra PYTHONPATH setup.
    sys.path.insert(0, str(ROOT_DIR))

from app.services.split_review_followup_ledger import (
    record_split_review_followup_ledger_entry,
    record_split_review_followup_ledger_transition,
    resolve_split_review_followup_ledger_packet,
    summarize_split_review_followup_ledger,
)

_REVIEW_ACTIONS: dict[str, dict[str, str]] = {
    "run_entry_timing_split_review": {
        "axis": "entry_timing",
        "target_key": "entry_timing_target",
        "preferred_key": "entry_timing_preferred_variant",
    },
    "run_execution_style_split_review": {
        "axis": "execution_style",
        "target_key": "execution_style_target",
        "preferred_key": "execution_style_preferred_variant",
    },
    "promote_entry_timing_branch_review": {
        "axis": "entry_timing",
        "target_key": "entry_timing_target",
        "preferred_key": "entry_timing_preferred_variant",
    },
    "promote_execution_style_branch_review": {
        "axis": "execution_style",
        "target_key": "execution_style_target",
        "preferred_key": "execution_style_preferred_variant",
    },
    "promote_preferred_branch_review": {
        "axis": "dynamic",
        "target_key": "",
        "preferred_key": "",
    },
    "reduce_baseline_allocation_review": {
        "axis": "dynamic",
        "target_key": "",
        "preferred_key": "",
    },
    "review_edge_kill_condition": {
        "axis": "dynamic",
        "target_key": "",
        "preferred_key": "",
    },
}

_DECISION_STATUSES = [
    "ACKED",
    "COMPLETED",
    "REJECTED",
    "PROMOTE_CONFIRMED",
    "REDUCE_CONFIRMED",
    "KILL_REVIEW_ESCALATED",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a concrete follow-up packet for split-review actions from the latest operator priority."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--action",
        default="auto",
        choices=["auto", *sorted(_REVIEW_ACTIONS)],
        help="Pick a specific split-review action or let the script choose the highest-priority split action.",
    )
    parser.add_argument("--report-dir", default="reports/operations/split_review_followups")
    parser.add_argument("--ledger-path", default="reports/operations/split_review_followups/review_ledger.jsonl")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-write-ledger", action="store_true")
    parser.add_argument(
        "--transition-status",
        default="",
        choices=["", *_DECISION_STATUSES],
        help="Append a decision/status transition to the latest recorded packet instead of generating a new packet.",
    )
    parser.add_argument("--packet-id", default="")
    parser.add_argument("--decision-actor", default="")
    parser.add_argument("--decision-notes", default="")
    parser.add_argument("--transition-reason", default="")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


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


def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _operator_action_priority(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    dashboard_source = _dict(
        (((dashboard_payload or {}).get("signal_funnel") or {}).get("operator_action_priority"))
    )
    validation_source = _dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("operator_action_priority_summary"))
    )
    return dashboard_source or validation_source


def _edge_experiment_review(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    dashboard_source = _dict(
        (((dashboard_payload or {}).get("signal_funnel") or {}).get("edge_experiment_review"))
    )
    validation_source = _dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("edge_experiment_review_summary"))
    )
    source = dashboard_source or validation_source
    source_summary = _dict(source.get("source_summary"))
    return {
        "edge_state": str(source.get("edge_state") or "insufficient_edge_measurement"),
        "closed_trade_count": int(source.get("closed_trade_count", 0) or 0),
        "true_edge_ratio": round(_float(source.get("true_edge_ratio")), 4),
        "recent_true_edge_ratio": round(_float(source.get("recent_true_edge_ratio")), 4),
        "prior_true_edge_ratio": round(_float(source.get("prior_true_edge_ratio")), 4),
        "edge_decay_rate": round(_float(source.get("edge_decay_rate")), 4),
        "entry_timing_preferred_variant": str(
            source.get("entry_timing_preferred_variant") or source_summary.get("entry_timing_preferred_variant") or "none"
        ),
        "execution_style_preferred_variant": str(
            source.get("execution_style_preferred_variant")
            or source_summary.get("execution_style_preferred_variant")
            or "none"
        ),
        "edge_proof_goal_closed_trades": int(source.get("edge_proof_goal_closed_trades", 0) or 0),
        "remaining_closed_trades_to_edge_proof_goal": int(
            source.get("remaining_closed_trades_to_edge_proof_goal", 0) or 0
        ),
        "edge_proof_posture": dict(source.get("edge_proof_posture") or {}),
        "daily_edge_kpis": dict(source.get("daily_edge_kpis") or {}),
        "summary": str(source.get("summary") or ""),
    }


def _edge_evolution_rule(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    dashboard_source = _dict(
        (((dashboard_payload or {}).get("signal_funnel") or {}).get("edge_evolution_rule"))
    )
    validation_source = _dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("edge_evolution_rule_summary"))
    )
    source = dashboard_source or validation_source
    source_summary = _dict(source.get("source_summary"))
    promotion_candidate = _dict(source.get("promotion_candidate"))
    closed_loop_feedback = _dict(source.get("closed_loop_feedback"))
    return {
        "evolution_state": str(source.get("evolution_state") or "insufficient_sample"),
        "recommended_action": str(source.get("recommended_action") or "keep_current_baseline"),
        "allocation_bias": str(source.get("allocation_bias") or "hold_current_baseline"),
        "confidence": str(source.get("confidence") or "low"),
        "recommendation_strength": str(source.get("recommendation_strength") or "baseline"),
        "kill_review_triggered": bool(source.get("kill_review_triggered", False)),
        "promotion_candidate_axis": str(
            source.get("promotion_candidate_axis") or promotion_candidate.get("axis") or "none"
        ),
        "promotion_candidate_variant": str(
            source.get("promotion_candidate_variant") or promotion_candidate.get("preferred_variant") or "none"
        ),
        "closed_loop_confirmation_state": str(
            source.get("closed_loop_confirmation_state")
            or closed_loop_feedback.get("confirmation_state")
            or "not_available"
        ),
        "summary": str(source.get("summary") or ""),
        "source_summary": source_summary,
    }


def _approval_strip(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    dashboard_strip = _dict((dashboard_payload or {}).get("approval_strip_summary"))
    validation_strip = _dict(
        (((validation_payload or {}).get("validation_report") or {}).get("approval_strip_summary"))
    )
    return {
        "dashboard": dashboard_strip,
        "validation": validation_strip,
    }


def _select_action(priority: dict[str, Any], edge_evolution: dict[str, Any], requested_action: str) -> tuple[str, str]:
    if requested_action != "auto":
        return requested_action, "explicit_request"

    top_action = str(priority.get("top_action") or "")
    if top_action in _REVIEW_ACTIONS:
        return top_action, "top_action"

    for row in list(priority.get("next_actions") or []):
        action = str(_dict(row).get("action") or "")
        if action in _REVIEW_ACTIONS:
            return action, "next_actions"
    evolution_action = str(edge_evolution.get("recommended_action") or "")
    if evolution_action in _REVIEW_ACTIONS:
        return evolution_action, "edge_evolution"
    return "", "no_review_action_available"


def _preferred_dynamic_axis(
    *,
    edge_evolution: dict[str, Any],
    experiment_context: dict[str, Any],
) -> tuple[str, str]:
    promotion_axis = str(edge_evolution.get("promotion_candidate_axis") or "none")
    promotion_variant = str(edge_evolution.get("promotion_candidate_variant") or "none")
    if promotion_axis == "entry_timing":
        return promotion_axis, promotion_variant or str(experiment_context.get("entry_timing_preferred_variant") or "none")
    if promotion_axis == "execution_style":
        return promotion_axis, promotion_variant or str(experiment_context.get("execution_style_preferred_variant") or "none")

    entry_target = _dict(experiment_context.get("entry_timing_target"))
    if entry_target.get("symbol"):
        return "entry_timing", str(experiment_context.get("entry_timing_preferred_variant") or promotion_variant or "none")
    execution_target = _dict(experiment_context.get("execution_style_target"))
    if execution_target.get("symbol"):
        return "execution_style", str(
            experiment_context.get("execution_style_preferred_variant") or promotion_variant or "none"
        )
    return str(promotion_axis or "branch"), str(promotion_variant or "none")


def _candidate_focus_fallback(experiment_context: dict[str, Any]) -> dict[str, Any]:
    return _dict(experiment_context.get("accepted_candidate_focus")) or _dict(
        experiment_context.get("blocked_candidate_focus")
    )


def _self_target_split_fallback(
    *,
    action: str,
    priority: dict[str, Any],
    edge_experiment: dict[str, Any],
    edge_evolution: dict[str, Any],
    requested_symbol: str,
) -> dict[str, Any] | None:
    spec = _REVIEW_ACTIONS.get(action)
    if not spec:
        return None
    axis = str(spec.get("axis") or "").strip()
    if axis not in {"entry_timing", "execution_style"}:
        return None
    symbol = str(requested_symbol or "").strip().upper()
    if not symbol:
        return None

    context = _dict(priority.get("experiment_context"))
    preferred_variant = str(context.get(spec["preferred_key"]) or "").strip()
    if not preferred_variant or preferred_variant == "none":
        if axis == "entry_timing":
            preferred_variant = str(edge_experiment.get("entry_timing_preferred_variant") or "").strip()
        else:
            preferred_variant = str(edge_experiment.get("execution_style_preferred_variant") or "").strip()
    if (
        (not preferred_variant or preferred_variant == "none")
        and str(edge_evolution.get("promotion_candidate_axis") or "").strip() == axis
    ):
        preferred_variant = str(edge_evolution.get("promotion_candidate_variant") or "").strip()
    if not preferred_variant or preferred_variant == "none":
        return None

    focus = _candidate_focus_fallback(context)
    return {
        "action": action,
        "axis": axis,
        "preferred_variant": preferred_variant,
        "symbol": symbol,
        "status": "SYMBOL_SELF_TARGET",
        "strategy_family": str(focus.get("strategy_family") or priority.get("action_family") or ""),
        "block_reason": str(focus.get("block_reason") or ""),
        "focus_source": "self_target_fallback",
    }


def _target_from_priority(
    priority: dict[str, Any],
    edge_evolution: dict[str, Any],
    action: str,
    *,
    symbol: str,
    edge_experiment: dict[str, Any],
) -> dict[str, Any] | None:
    spec = _REVIEW_ACTIONS.get(action)
    if not spec:
        return None
    context = _dict(priority.get("experiment_context"))
    target: dict[str, Any] = {}
    axis = str(spec.get("axis") or "branch")
    preferred_variant = "none"
    if axis in {"entry_timing", "execution_style"}:
        target = _dict(context.get(spec["target_key"]))
        preferred_variant = str(context.get(spec["preferred_key"]) or "none")
    else:
        axis, preferred_variant = _preferred_dynamic_axis(
            edge_evolution=edge_evolution,
            experiment_context=context,
        )
        if axis == "entry_timing":
            target = _dict(context.get("entry_timing_target"))
        elif axis == "execution_style":
            target = _dict(context.get("execution_style_target"))
        if not target:
            target = _candidate_focus_fallback(context)

    if not target:
        matching_row = next(
            (
                _dict(row)
                for row in list(priority.get("next_actions") or [])
                if str(_dict(row).get("action") or "") == action
            ),
            {},
        )
        if matching_row.get("target_symbol"):
            target = {
                "symbol": str(matching_row.get("target_symbol") or ""),
                "status": str(matching_row.get("target_status") or ""),
                "strategy_family": str(matching_row.get("target_family") or ""),
                "block_reason": str(matching_row.get("target_block_reason") or ""),
                "focus_source": str(matching_row.get("target_focus_source") or ""),
            }
    if not target:
        fallback = _self_target_split_fallback(
            action=action,
            priority=priority,
            edge_experiment=edge_experiment,
            edge_evolution=edge_evolution,
            requested_symbol=symbol,
        )
        if fallback:
            return fallback
        return None
    return {
        "action": action,
        "axis": axis,
        "preferred_variant": preferred_variant,
        "symbol": str(target.get("symbol") or ""),
        "status": str(target.get("status") or ""),
        "strategy_family": str(target.get("strategy_family") or ""),
        "block_reason": str(target.get("block_reason") or ""),
        "focus_source": str(target.get("focus_source") or ""),
    }


def _review_steps(
    action: str,
    target: dict[str, Any] | None,
    *,
    edge_experiment: dict[str, Any],
    edge_evolution: dict[str, Any],
) -> list[str]:
    target_contract = _dict(target)
    symbol = str(target_contract.get("symbol") or "target_symbol")
    family = str(target_contract.get("strategy_family") or "unknown_family")
    preferred_variant = str(target_contract.get("preferred_variant") or "none")
    axis = str(target_contract.get("axis") or "branch")
    if action == "run_entry_timing_split_review":
        return [
            f"Compare the preferred entry timing branch `{preferred_variant}` against the current target row `{symbol}` / `{family}`.",
            "Keep approval, sizing, and rollout authority unchanged; this packet is advisory research context only.",
            "After new closes arrive, re-read score_to_outcome_funnel and outcome_attribution before changing entry design.",
        ]
    if action == "run_execution_style_split_review":
        return [
            f"Compare the preferred execution style `{preferred_variant}` against the current target row `{symbol}` / `{family}`.",
            "Keep approval, sizing, and rollout authority unchanged; this packet is advisory research context only.",
            "After new fills and closes arrive, re-read fill-capture and post-cost drag before changing execution mode.",
        ]
    if action == "reduce_baseline_allocation_review":
        return [
            (
                f"Re-check whether the preferred `{axis}` branch `{preferred_variant}` still outperforms the baseline "
                f"for `{symbol}` / `{family}` before reducing any baseline allocation."
            ),
            (
                f"Treat `true_edge_ratio={edge_experiment.get('true_edge_ratio')}` and "
                f"`edge_decay_rate={edge_experiment.get('edge_decay_rate')}` as advisory evidence only; "
                "do not change rollout or sizing authority from this packet."
            ),
            (
                f"If edge deterioration persists after the next closes, escalate from "
                f"`{edge_evolution.get('recommended_action') or action}` into `review_edge_kill_condition`."
            ),
        ]
    if action == "review_edge_kill_condition":
        return [
            (
                f"Review whether the preferred `{axis}` branch `{preferred_variant}` is still weak enough on "
                f"`{symbol}` / `{family}` to justify edge-based kill review."
            ),
            "Keep kill-switch and close-only authority outside this packet; this output is advisory research context only.",
            "Reconcile kill-condition posture with the latest post-cost closes, fill-capture gap, and rollout posture before escalating.",
        ]
    if action in {
        "promote_entry_timing_branch_review",
        "promote_execution_style_branch_review",
        "promote_preferred_branch_review",
    }:
        return [
            (
                f"Validate that the preferred `{axis}` branch `{preferred_variant}` still outperforms the baseline "
                f"on `{symbol}` / `{family}` with enough post-cost sample to justify promotion review."
            ),
            (
                "Keep approval, rollout, and lifecycle authority unchanged until validation and checklist "
                "surfaces separately agree with the promotion posture."
            ),
            (
                f"Use `evolution_state={edge_evolution.get('evolution_state')}` and "
                f"`allocation_bias={edge_evolution.get('allocation_bias')}` as the current promotion context."
            ),
        ]
    return ["No split review action is currently available from operator_action_priority."]


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger_summary = _dict(payload.get("review_followup_ledger_summary"))
    lines = [
        "# Split Review Followup",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- packet_id: {payload.get('packet_id', '') or 'none'}",
        f"- symbol: {payload['symbol']}",
        f"- universe: {payload['universe']}",
        f"- days: {payload['days']}",
        f"- status: {payload['status']}",
        f"- selected_action: {payload['selected_action']}",
        f"- selection_reason: {payload['selection_reason']}",
        "",
        "## Target Contract",
        "",
    ]
    target = _dict(payload.get("target_contract"))
    if target:
        lines.extend(
            [
                f"- action: {target.get('action')}",
                f"- axis: {target.get('axis')}",
                f"- preferred_variant: {target.get('preferred_variant')}",
                f"- symbol: {target.get('symbol')}",
                f"- status: {target.get('status')}",
                f"- strategy_family: {target.get('strategy_family')}",
                f"- block_reason: {target.get('block_reason')}",
                f"- focus_source: {target.get('focus_source')}",
            ]
        )
    else:
        lines.append("- target contract unavailable")
    lines.extend(
        [
            "",
            "## Operator Context",
            "",
            (
                f"- operator_action_priority: top_action={payload['operator_action_priority'].get('top_action')} "
                f"| priority={payload['operator_action_priority'].get('priority_level')} "
                f"| source={payload['operator_action_priority'].get('priority_source')}"
            ),
            f"- top_reason: {payload['operator_action_priority'].get('top_reason')}",
            (
                f"- edge_experiment: state={payload['edge_experiment_review'].get('edge_state')} "
                f"| proof={dict(payload['edge_experiment_review'].get('edge_proof_posture') or {}).get('state', 'unknown')}/"
                f"{dict(payload['edge_experiment_review'].get('edge_proof_posture') or {}).get('claim_state', 'unknown')} "
                f"| closes={int(dict(payload['edge_experiment_review'].get('daily_edge_kpis') or {}).get('closed_trade_count', payload['edge_experiment_review'].get('closed_trade_count', 0)) or 0)}/"
                f"{int(payload['edge_experiment_review'].get('edge_proof_goal_closed_trades', 0) or 0)} "
                f"| remaining={int(payload['edge_experiment_review'].get('remaining_closed_trades_to_edge_proof_goal', 0) or 0)} "
                f"| regime={dict(payload['edge_experiment_review'].get('daily_edge_kpis') or {}).get('regime_dependency_state', 'not_available')} "
                f"| true_edge={dict(payload['edge_experiment_review'].get('daily_edge_kpis') or {}).get('true_edge_ratio', payload['edge_experiment_review'].get('true_edge_ratio'))} "
                f"| decay={dict(payload['edge_experiment_review'].get('daily_edge_kpis') or {}).get('edge_decay_rate', payload['edge_experiment_review'].get('edge_decay_rate'))}"
            ),
            (
                f"- edge_evolution: state={payload['edge_evolution_rule'].get('evolution_state')} "
                f"| action={payload['edge_evolution_rule'].get('recommended_action')} "
                f"| bias={payload['edge_evolution_rule'].get('allocation_bias')} "
                f"| promotion={payload['edge_evolution_rule'].get('promotion_candidate_axis')}/"
                f"{payload['edge_evolution_rule'].get('promotion_candidate_variant')}"
            ),
            "",
            "## Followup Ledger",
            "",
            (
                f"- available: {bool(ledger_summary.get('available', False))} "
                f"| recent_entries={int(ledger_summary.get('recent_entry_count', 0) or 0)} "
                f"| last_generated_status={ledger_summary.get('last_status', 'none')} "
                f"| last_decision_status={ledger_summary.get('last_decision_status', 'none')}"
            ),
            (
                f"- last_action: {ledger_summary.get('last_action', 'none')} "
                f"| last_followup_command: "
                f"{ledger_summary.get('last_followup_command', '') or 'none'}"
            ),
            f"- ledger_path: {ledger_summary.get('ledger_path', '') or 'none'}",
            f"- summary: {ledger_summary.get('summary', '')}",
            "",
            "## Review Steps",
            "",
        ]
    )
    for step in payload.get("review_steps") or []:
        lines.append(f"- {step}")
    lines.extend(
        [
            "",
            "## Raw Payload",
            "",
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            "```",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    generated_at = _now()
    ledger_path = ROOT_DIR / args.ledger_path
    transition_status = str(getattr(args, "transition_status", "") or "")
    if transition_status:
        if bool(getattr(args, "no_write_ledger", False)):
            raise RuntimeError("--transition-status requires ledger writes")
        transition_entry = record_split_review_followup_ledger_transition(
            symbol=args.symbol,
            universe=args.universe,
            decision_status=transition_status,
            packet_id=str(getattr(args, "packet_id", "") or "").strip() or None,
            selected_action=args.action,
            decision_actor=str(getattr(args, "decision_actor", "") or ""),
            decision_notes=str(getattr(args, "decision_notes", "") or ""),
            transition_reason=str(getattr(args, "transition_reason", "") or ""),
            ledger_path=ledger_path,
        )
        resolved_packet = resolve_split_review_followup_ledger_packet(
            symbol=args.symbol,
            universe=args.universe,
            packet_id=str(transition_entry.get("packet_id") or ""),
            ledger_path=ledger_path,
        )
        payload = {
            "mode": "record_transition",
            "generated_at": generated_at.isoformat(),
            "symbol": args.symbol.upper(),
            "universe": args.universe,
            "packet_id": str(transition_entry.get("packet_id") or ""),
            "status": str(transition_entry.get("status") or transition_status),
            "selected_action": str(transition_entry.get("selected_action") or "none"),
            "decision_actor": str(transition_entry.get("decision_actor") or ""),
            "decision_notes": str(transition_entry.get("decision_notes") or ""),
            "transition_reason": str(transition_entry.get("transition_reason") or ""),
            "target_contract": _dict(transition_entry.get("target_contract")),
            "review_followup_ledger_packet": resolved_packet,
            "review_followup_ledger_summary": summarize_split_review_followup_ledger(
                symbol=args.symbol,
                universe=args.universe,
                ledger_path=ledger_path,
            ),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
        return 0

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
    priority = _operator_action_priority(dashboard_payload=dashboard, validation_payload=validation)
    edge_experiment = _edge_experiment_review(
        dashboard_payload=dashboard,
        validation_payload=validation,
    )
    edge_evolution = _edge_evolution_rule(
        dashboard_payload=dashboard,
        validation_payload=validation,
    )
    selected_action, selection_reason = _select_action(priority, edge_evolution, args.action)
    target_contract = _target_from_priority(
        priority,
        edge_evolution,
        selected_action,
        symbol=args.symbol,
        edge_experiment=edge_experiment,
    )
    status = "READY"
    if not selected_action:
        status = "NO_REVIEW_ACTION_AVAILABLE"
    elif not target_contract:
        status = "NO_TARGET"

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "packet_id": f"review_followup:{uuid4().hex}",
        "symbol": args.symbol.upper(),
        "universe": args.universe,
        "days": args.days,
        "status": status,
        "selected_action": selected_action or "none",
        "selection_reason": selection_reason,
        "operator_action_priority": {
            "top_action": str(priority.get("top_action") or "continue_runtime_monitoring"),
            "top_reason": str(priority.get("top_reason") or ""),
            "priority_level": str(priority.get("priority_level") or "monitor"),
            "priority_source": str(priority.get("priority_source") or "monitor"),
        },
        "edge_experiment_review": edge_experiment,
        "edge_evolution_rule": edge_evolution,
        "approval_strips": _approval_strip(
            dashboard_payload=dashboard,
            validation_payload=validation,
        ),
        "target_contract": target_contract,
        "review_steps": _review_steps(
            selected_action,
            target_contract,
            edge_experiment=edge_experiment,
            edge_evolution=edge_evolution,
        ),
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"split_review_followup_{args.symbol.upper()}_{ts}.md"
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    if not args.no_write_ledger:
        recorded_entry = record_split_review_followup_ledger_entry(payload, ledger_path=ledger_path)
        payload["packet_id"] = str(recorded_entry.get("packet_id") or payload.get("packet_id") or "")
    payload["review_followup_ledger_summary"] = summarize_split_review_followup_ledger(
        symbol=args.symbol,
        universe=args.universe,
        ledger_path=ledger_path,
    )

    if not args.no_write_report:
        _write_report(report_path, payload)

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
