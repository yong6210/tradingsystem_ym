#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
_REQUEST_RETRY_ATTEMPTS = 3
_REQUEST_RETRY_BASE_DELAY_SECONDS = 0.5
_REQUEST_TIMEOUT_SECONDS = 90


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MICRO_LIVE preflight checks against the local API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--candidate-limit", type=int, default=10)
    parser.add_argument("--report-dir", default="reports/operations/micro_live_preflight")
    parser.add_argument("--no-write-report", action="store_true")
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
    last_error: RuntimeError | None = None
    for attempt in range(1, _REQUEST_RETRY_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code >= 500 or "database is locked" in payload.lower()
            last_error = RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {payload}")
            if retryable and attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc
        except URLError as exc:
            last_error = RuntimeError(f"{method.upper()} {path} failed: {exc.reason}")
            if attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc
        except TimeoutError as exc:
            last_error = RuntimeError(f"{method.upper()} {path} timed out after {_REQUEST_TIMEOUT_SECONDS}s")
            if attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc
    assert last_error is not None
    raise last_error


def _truthy_ready(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status", "")).lower()
    checks = payload.get("checks") or {}
    return status == "ready" and all(bool(value) for value in checks.values())


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


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

    deployment_summary = dict(surface.get("deployment_approval_summary") or {})
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
        f"- {label}: approve={summary.get('approve_value', 'n/a')} | "
        f"align={summary.get('align_value', 'n/a')} | "
        f"act={summary.get('act_value', 'continue_runtime_monitoring')} | "
        f"priority={summary.get('act_priority_level', 'monitor')}"
    )


def _surface_allows_preflight(summary: dict[str, str]) -> bool:
    approve_value = str(summary.get("approve_value") or "").strip().lower()
    return approve_value not in {"runtime no_go", "validation no_go", "validation/checklist no_go", "entry gate blocked"}


def _candidate_availability_check(
    *,
    candidate: dict[str, Any] | None,
    dashboard_strip: dict[str, str],
) -> dict[str, str]:
    if candidate:
        return {
            "name": "candidate_available",
            "status": "PASS",
            "message": (
                f"{candidate.get('symbol', '')} {candidate.get('strategy_family', '')} "
                f"{candidate.get('deployment_go_no_go', '') or candidate.get('operator_status', '')}"
            ),
        }
    return {
        "name": "candidate_available",
        "status": "PASS",
        "message": (
            "No accepted scanner candidate is live right now; runtime may stay open and wait for the next "
            f"eligible session candidate. act={dashboard_strip.get('act_value', '')}"
        ),
    }


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
    detail = _edge_experiment_detail_parts(summary)
    proof_goal = max(int(detail["proof_goal_closed_trades"] or 0), 0)
    remaining = max(int(detail["remaining_closed_trades_to_edge_proof_goal"] or 0), 0)
    if detail["proof_state"] == "sample_building":
        return (
            "Advisory only: edge proof is still sample-building; treat split preferences as directional while "
            f"{remaining} closed trades remain to the {proof_goal}-close proof goal."
        )
    if detail["proof_state"] == "regime_limited":
        return (
            "Advisory only: edge proof goal is met, but regime dependency is still active; do not generalize "
            "promotion until weaker regimes accumulate confirming closes."
        )
    if detail["proof_state"] == "proof_goal_met_but_edge_weak":
        return (
            "Advisory only: the proof goal is met, but current true-edge/decay still looks weak; keep allocation "
            "changes in research mode until metrics stabilize."
        )
    edge_state = str(summary.get("edge_state") or "")
    entry_timing = str(summary.get("entry_timing_preferred_variant") or "none")
    execution_style = str(summary.get("execution_style_preferred_variant") or "none")
    if edge_state == "fragile_edge":
        return (
            "Advisory only: post-cost edge is fragile; run controlled split review "
            f"with entry_timing={entry_timing} and execution_style={execution_style} before widening live scope."
        )
    if edge_state == "watch_edge":
        return (
            "Advisory only: post-cost edge is unstable; prefer controlled split review "
            f"with entry_timing={entry_timing} and execution_style={execution_style} over structural rewrites."
        )
    if edge_state == "insufficient_edge_measurement":
        return "Advisory only: collect more closed post-cost trades before treating edge experiment output as decisive."
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
            "Advisory only: edge evolution now points to kill review; hold live expansion and run "
            f"{action} before trusting further allocation."
        )
    if evolution_state == "reduce_candidate":
        return (
            "Advisory only: edge evolution points to baseline reduction; keep branch tests active but treat "
            f"{action} as the next allocation review."
        )
    if evolution_state == "promote_candidate":
        return (
            "Advisory only: preferred branch now has promotion-review posture; review "
            f"{axis}={variant} with {action} before broader rollout changes."
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


def _operator_action_priority_summary(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    dashboard_source = dict((((dashboard_payload or {}).get("signal_funnel") or {}).get("operator_action_priority") or {}))
    validation_source = dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("operator_action_priority_summary") or {})
    )
    return dashboard_source or validation_source


def _experiment_review_target(
    operator_action_priority: dict[str, Any] | None,
    *,
    target_key: str,
    preferred_key: str,
    action: str,
) -> dict[str, Any] | None:
    priority = dict(operator_action_priority or {})
    context = dict(priority.get("experiment_context") or {})
    target = dict(context.get(target_key) or {})
    if not target:
        return None
    return {
        "action": action,
        "preferred_variant": str(context.get(preferred_key) or "none"),
        "symbol": str(target.get("symbol") or ""),
        "status": str(target.get("status") or ""),
        "strategy_family": str(target.get("strategy_family") or ""),
        "block_reason": str(target.get("block_reason") or ""),
        "focus_source": str(target.get("focus_source") or ""),
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
    return line


def _split_review_followup_command(*, symbol: str, universe: str, days: int, action: str) -> str:
    return (
        f"./.venv/bin/python scripts/run_split_review_followup.py "
        f"--symbol {symbol.upper()} --universe {universe} --days {days} --action {action}"
    )


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
    lines.append("# MICRO_LIVE Preflight")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- universe: {payload['universe']}")
    lines.append(f"- overall_status: {payload['overall_status']}")
    lines.append("")
    lines.append("## Key Decision")
    lines.append("")
    lines.append(f"- result: {payload['overall_status']}")
    lines.append(f"- summary: {payload['summary_line']}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for item in payload["checks"]:
        lines.append(f"- [{item['status']}] {item['name']}: {item['message']}")
    lines.append("")
    lines.append("## Approval Surfaces")
    lines.append("")
    for row in payload.get("approval_surfaces") or []:
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
    experiment_targets = payload.get("experiment_review_targets") or {}
    lines.append(f"- {_experiment_review_target_line('entry_timing_review_target', experiment_targets.get('entry_timing'))}")
    lines.append(f"- {_experiment_review_target_line('execution_style_review_target', experiment_targets.get('execution_style'))}")
    representative_candidates = payload.get("representative_candidates") or {}
    lines.append(f"- {_representative_candidate_line('accepted_candidate_focus', representative_candidates.get('accepted'))}")
    lines.append(f"- {_representative_candidate_line('blocked_candidate_focus', representative_candidates.get('blocked'))}")
    lines.append("")
    lines.append("## Candidate")
    lines.append("")
    candidate = payload.get("candidate") or {}
    if candidate:
        lines.append(f"- plan_id: {candidate.get('plan_id', '')}")
        lines.append(f"- symbol: {candidate.get('symbol', '')}")
        lines.append(f"- family: {candidate.get('strategy_family', '')}")
        lines.append(f"- candidate_surface: {candidate.get('deployment_go_no_go', '') or candidate.get('operator_status', '')}")
        lines.append(f"- expected_summary: {candidate.get('expected_summary', '')}")
    else:
        lines.append("- no candidate selected")
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

    ready = _request_json(args.base_url, "GET", "/health/ready")
    dashboard = _request_json(
        args.base_url,
        "GET",
        "/execution/operator-dashboard",
        query={"symbol": args.symbol, "universe": args.universe, "days": args.days},
    )
    safety = _request_json(
        args.base_url,
        "GET",
        "/execution/safety-state",
        query={"symbol": args.symbol},
    )
    reconcile = _request_json(
        args.base_url,
        "POST",
        "/execution/reconcile",
        query={"apply_lock": "false", "auto_resolve": "false"},
        body={"symbol": args.symbol},
    )
    validation = _request_json(
        args.base_url,
        "POST",
        "/validation/report",
        query={"symbol": args.symbol, "refresh": "false"},
    )
    checklist = _request_json(
        args.base_url,
        "POST",
        "/operations/checklist",
        query={"symbol": args.symbol, "write_report": "false"},
    )
    alerts = _request_json(
        args.base_url,
        "GET",
        "/alerts/metrics",
        query={"days": args.days, "write_report": "false"},
    )
    scanner = _request_json(
        args.base_url,
        "GET",
        "/scanner/top",
        query={"universe": args.universe, "limit": args.candidate_limit},
    )

    candidate: dict[str, Any] | None = None
    if isinstance(scanner, list) and scanner:
        matching = [row for row in scanner if str(row.get("symbol", "")).upper() == args.symbol.upper()]
        candidate = matching[0] if matching else scanner[0]
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
    operator_action_priority = _operator_action_priority_summary(
        dashboard_payload=dashboard,
        validation_payload=validation,
    )
    experiment_review_targets = {
        "entry_timing": _experiment_review_target(
            operator_action_priority,
            target_key="entry_timing_target",
            preferred_key="entry_timing_preferred_variant",
            action="run_entry_timing_split_review",
        ),
        "execution_style": _experiment_review_target(
            operator_action_priority,
            target_key="execution_style_target",
            preferred_key="execution_style_preferred_variant",
            action="run_execution_style_split_review",
        ),
    }
    for target in experiment_review_targets.values():
        if target:
            target["followup_command"] = _split_review_followup_command(
                symbol=args.symbol,
                universe=args.universe,
                days=args.days,
                action=str(target.get("action") or ""),
            )
    representative_candidates = _representative_candidates(dashboard)

    checks: list[dict[str, str]] = []
    checks.append(
        {
            "name": "health_ready",
            "status": _status(_truthy_ready(ready)),
            "message": f"health status={ready.get('status', 'unknown')} checks={ready.get('checks', {})}",
        }
    )
    checks.append(
        {
            "name": "auto_trading_enabled",
            "status": _status(bool(dashboard.get("auto_trading_enabled", False))),
            "message": f"execution_mode={dashboard.get('execution_mode', 'unknown')}",
        }
    )
    checks.append(
        {
            "name": "new_entries_allowed",
            "status": _status(bool(dashboard.get("new_entries_allowed", False))),
            "message": (
                f"approve={dashboard_strip.get('approve_value', '')} | "
                f"align={dashboard_strip.get('align_value', '')} | "
                f"act={dashboard_strip.get('act_value', '')} | "
                f"reason={dashboard.get('blocking_reason_message') or dashboard_strip.get('approve_reason') or dashboard_strip.get('act_reason') or 'new entries allowed'}"
            ),
        }
    )
    checks.append(
        {
            "name": "validation_language",
            "status": _status(_surface_allows_preflight(validation_strip)),
            "message": (
                f"approve={validation_strip.get('approve_value', '')} | "
                f"align={validation_strip.get('align_value', '')} | "
                f"act={validation_strip.get('act_value', '')} | "
                f"reason={validation_strip.get('approve_reason', '') or validation_strip.get('act_reason', '')}"
            ),
        }
    )
    checks.append(
        {
            "name": "checklist_language",
            "status": _status(_surface_allows_preflight(checklist_strip)),
            "message": (
                f"approve={checklist_strip.get('approve_value', '')} | "
                f"align={checklist_strip.get('align_value', '')} | "
                f"act={checklist_strip.get('act_value', '')} | "
                f"reason={checklist_strip.get('approve_reason', '') or checklist_strip.get('act_reason', '')}"
            ),
        }
    )
    checks.append(
        {
            "name": "safety_state",
            "status": _status(
                not bool(safety.get("kill_switch_active", False))
                and not bool(safety.get("close_only_active", False))
                and not bool(safety.get("config_close_only_active", False))
            ),
            "message": f"kill={safety.get('kill_switch_active', False)} close_only={safety.get('close_only_active', False)} config_close_only={safety.get('config_close_only_active', False)}",
        }
    )
    reconcile_summary = reconcile if isinstance(reconcile, dict) else {}
    reconcile_healthy = bool(reconcile_summary.get("healthy", not bool(reconcile_summary.get("mismatches", []))))
    checks.append(
        {
            "name": "reconciliation",
            "status": _status(reconcile_healthy),
            "message": f"healthy={reconcile_summary.get('healthy', False)} severity={reconcile_summary.get('highest_severity', 'INFO')}",
        }
    )
    latest_validation_alert = (alerts.get("latest_validation_alert") or {}) if isinstance(alerts, dict) else {}
    checks.append(
        {
            "name": "alert_channel",
            "status": _status(bool(latest_validation_alert) or bool((alerts.get("overall") or {}).get("total", 0))),
            "message": f"latest_validation_alert={bool(latest_validation_alert)}",
        }
    )
    checks.append(_candidate_availability_check(candidate=candidate, dashboard_strip=dashboard_strip))

    failed = [item for item in checks if item["status"] != "PASS"]
    overall_status = "READY_FOR_MICRO_LIVE" if not failed else "NOT_READY"
    next_steps = [item["message"] for item in failed] if failed else ["Proceed to the live go-live checklist and final operator sign-off."]
    advisory_next_step = _edge_experiment_next_step(edge_experiment_review)
    if advisory_next_step:
        next_steps.append(advisory_next_step)
    edge_evolution_next_step = _edge_evolution_next_step(edge_evolution_rule)
    if edge_evolution_next_step:
        next_steps.append(edge_evolution_next_step)
    review_followup_next_step = _review_followup_next_step(review_followup_ledger)
    if review_followup_next_step:
        next_steps.append(review_followup_next_step)
    targeted_reviews = [
        str(target.get("followup_command") or "")
        for target in experiment_review_targets.values()
        if target
    ]
    if targeted_reviews:
        next_steps.append("Advisory only: run split review packet(s) with " + "; ".join(targeted_reviews) + ".")
    summary_line = (
        "All preflight checks passed; MICRO_LIVE can proceed to final operator sign-off."
        if not failed
        else f"{len(failed)} blocking preflight check(s) remain."
    )

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbol": args.symbol.upper(),
        "universe": args.universe,
        "overall_status": overall_status,
        "summary_line": summary_line,
        "checks": checks,
        "candidate": candidate or {},
        "health_ready": ready,
        "operator_dashboard": dashboard,
        "operator_dashboard_summary": {
            "execution_mode": dashboard.get("execution_mode", ""),
            "auto_trading_enabled": dashboard.get("auto_trading_enabled", False),
            "new_entries_allowed": dashboard.get("new_entries_allowed", False),
            "blocking_reason_code": dashboard.get("blocking_reason_code", ""),
            "blocking_reason_message": dashboard.get("blocking_reason_message", ""),
            "approval_strip_summary": dashboard_strip,
        },
        "reconciliation": reconcile,
        "safety_state": safety,
        "validation_report": {
            "deployment_go_no_go": validation.get("deployment_go_no_go", ""),
            "deployment_code": validation.get("deployment_code", ""),
            "deployment_message": validation.get("deployment_message", ""),
            "playbook_go_no_go": validation.get("playbook_go_no_go", ""),
            "playbook_action": validation.get("playbook_action", ""),
            "approval_strip_summary": validation_strip,
        },
        "operations_checklist": {
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
        "experiment_review_targets": experiment_review_targets,
        "representative_candidates": representative_candidates,
        "alert_metrics_summary": {
            "latest_validation_alert": latest_validation_alert,
            "overall": (alerts.get("overall") or {}) if isinstance(alerts, dict) else {},
        },
        "next_steps": next_steps,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"micro_live_preflight_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
