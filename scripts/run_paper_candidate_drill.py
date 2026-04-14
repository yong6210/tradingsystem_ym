#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from http.client import RemoteDisconnected
from pathlib import Path
import socket
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
_REQUEST_RETRY_ATTEMPTS = 5
_REQUEST_RETRY_BASE_DELAY_SECONDS = 1.0
_REQUEST_TIMEOUT_SECONDS = 90


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a PAPER candidate drill for eligible strategy families against the local API."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default=None, help="Optional symbol pin. If omitted, pick the best eligible candidate.")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--families", default="trend_continuation,sweep_reversal")
    parser.add_argument("--candidate-limit", type=int, default=100)
    parser.add_argument("--include-manual-review", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--limit-symbols", type=int, default=30)
    parser.add_argument("--symbol-concurrency", type=int, default=4)
    parser.add_argument("--limit-1m", type=int, default=900)
    parser.add_argument("--limit-5m", type=int, default=500)
    parser.add_argument("--limit-15m", type=int, default=500)
    parser.add_argument("--submit-paper", action="store_true")
    parser.add_argument("--paper-scenario", default="fill", choices=["fill", "partial_fill", "cancel", "timeout", "reject", "attach_failure"])
    parser.add_argument(
        "--paper-lineage-override",
        action="store_true",
        help="Allow PAPER-only lineage override for eligible family candidates blocked by active-plan thesis duplication.",
    )
    parser.add_argument("--report-dir", default="reports/operations/paper_candidate_drill")
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
    last_error: RuntimeError | None = None
    for attempt in range(1, _REQUEST_RETRY_ATTEMPTS + 1):
        request = Request(url=url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code >= 500 or "database is locked" in payload.lower() or "sqlite busy" in payload.lower()
            last_error = RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {payload}")
            if retryable and attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc
        except (URLError, TimeoutError, socket.timeout, RemoteDisconnected) as exc:
            reason = exc.reason if isinstance(exc, URLError) else str(exc)
            last_error = RuntimeError(f"{method.upper()} {path} failed: {reason}")
            if attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc

    assert last_error is not None
    raise last_error


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _family_set(raw: str) -> set[str]:
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _scanner_candidate_strip_summary(row: dict[str, Any] | None) -> dict[str, str] | None:
    candidate = dict(row or {})
    if not candidate:
        return None
    deployment_state = str(candidate.get("deployment_go_no_go") or "MANUAL_REVIEW").upper()
    approve_value = "approval usable"
    if deployment_state == "NO_GO":
        approve_value = "runtime no_go"
    elif deployment_state == "MANUAL_REVIEW":
        approve_value = "manual review first"
    act_value = "continue_candidate_review_under_portfolio_caps"
    if str(candidate.get("block_reason") or ""):
        act_value = "review_candidate_block_reason"
    return {
        "primary_reason": str(candidate.get("deployment_message") or candidate.get("block_reason_message") or ""),
        "approve_value": approve_value,
        "approve_reason": str(candidate.get("deployment_message") or ""),
        "align_value": "candidate_surface",
        "align_reason": "scanner candidate surface is a runtime context layer",
        "act_value": act_value,
        "act_reason": str(candidate.get("block_reason_message") or candidate.get("deployment_message") or ""),
        "act_priority_level": "watch" if deployment_state == "MANUAL_REVIEW" else "monitor",
    }


def _approval_strip_summary(payload: dict[str, Any] | None) -> dict[str, str] | None:
    approval = dict(payload or {})
    if not approval:
        return None
    approval_state = str(approval.get("approval_state") or "").upper()
    deployment_go_no_go = str(approval.get("deployment_go_no_go") or "MANUAL_REVIEW").upper()
    playbook_go_no_go = str(approval.get("playbook_go_no_go") or deployment_go_no_go).upper()
    deployment_message = str(approval.get("deployment_message") or "").strip()
    playbook_message = str(approval.get("playbook_message") or "").strip()
    approve_value = "approval usable"
    if approval_state == "BLOCKED" or deployment_go_no_go == "NO_GO":
        approve_value = "execution blocked"
    elif approval_state == "APPROVED_MANUAL" or deployment_go_no_go == "MANUAL_REVIEW":
        approve_value = "manual review first"
    elif approval_state == "APPROVED_SHADOW":
        approve_value = "shadow only"
    align_value = "aligned" if deployment_go_no_go == playbook_go_no_go else "playbook_drift"
    priority_map = {
        "BLOCKED": "urgent",
        "APPROVED_MANUAL": "watch",
        "APPROVED_SHADOW": "watch",
        "APPROVED_AUTO": "monitor",
    }
    return {
        "primary_reason": deployment_message or playbook_message,
        "approve_value": approve_value,
        "approve_reason": deployment_message or playbook_message,
        "align_value": align_value,
        "align_reason": playbook_message or deployment_message,
        "act_value": str(approval.get("playbook_action") or "review_execution_gate_before_submit"),
        "act_reason": playbook_message or deployment_message,
        "act_priority_level": priority_map.get(approval_state, "monitor"),
    }


def _edge_experiment_summary(validation_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    source = dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("edge_experiment_review_summary") or {})
    )
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


def _top_refresh_block(diag: dict[str, Any] | None) -> tuple[str | None, int]:
    source = dict(diag or {})
    for key in (
        "hard_gate_block_counts",
        "generic_setup_block_counts",
        "router_block_counts",
        "reaction_skip_counts",
        "mode_block_counts",
        "setup_disable_counts",
        "legacy_router_reason_counts",
    ):
        counts = dict(source.get(key) or {})
        if counts:
            first_key = next(iter(counts))
            return str(first_key), int(counts.get(first_key, 0) or 0)
    return None, 0


def _symbol_refresh_summary(indicator_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    refresh = dict((indicator_payload or {}).get("refresh") or {})
    if not refresh:
        return None
    diagnostics = dict(refresh.get("plan_generation_diagnostics") or {})
    top_block_reason, top_block_count = _top_refresh_block(diagnostics)
    summary = {
        "symbol": str(refresh.get("symbol") or (indicator_payload or {}).get("symbol") or "").upper() or None,
        "updated": bool(refresh.get("updated", False)),
        "generated_plan_count": int(refresh.get("plans", 0) or 0),
        "active_signal_plan_count": int(refresh.get("active_signal_plan_count", 0) or 0),
        "active_zone_count": int(refresh.get("active_zone_count", diagnostics.get("active_zone_count", 0)) or 0),
        "regime_label": str(refresh.get("regime_label") or diagnostics.get("regime_profile") or "unknown"),
        "transition_state": str(refresh.get("transition_state") or diagnostics.get("transition_state") or "unknown"),
        "generation_state": str(diagnostics.get("generation_state") or "unknown"),
        "top_block_reason": top_block_reason,
        "top_block_count": int(top_block_count or 0),
        "plan_generation_diagnostics": diagnostics,
    }
    if summary["generated_plan_count"] > 0:
        summary["message"] = (
            f"{summary['symbol'] or 'symbol'} refresh generated {summary['generated_plan_count']} fresh plan(s); "
            f"scanner/portfolio eligibility is the remaining gate."
        )
    elif top_block_reason:
        summary["message"] = (
            f"{summary['symbol'] or 'symbol'} refresh generated 0 fresh plan(s) from {summary['active_zone_count']} active zone(s); "
            f"top block={top_block_reason} x{summary['top_block_count']} "
            f"under {summary['regime_label']}/{summary['transition_state']}."
        )
    else:
        summary["message"] = (
            f"{summary['symbol'] or 'symbol'} refresh generated 0 fresh plan(s) from {summary['active_zone_count']} active zone(s)."
        )
    return summary


def _edge_experiment_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "edge_experiment: unavailable"
    posture = dict(summary.get("edge_proof_posture") or {})
    kpis = dict(summary.get("daily_edge_kpis") or {})
    return (
        f"edge_experiment: state={summary.get('edge_state', 'insufficient_edge_measurement')} | "
        f"entry_timing={summary.get('entry_timing_preferred_variant', 'none')} | "
        f"execution_style={summary.get('execution_style_preferred_variant', 'none')} | "
        f"proof={posture.get('state', 'unknown')}/{posture.get('claim_state', 'unknown')} | "
        f"closes={int(kpis.get('closed_trade_count', 0) or 0)}/{int(summary.get('edge_proof_goal_closed_trades', 0) or 0)} | "
        f"remaining={int(summary.get('remaining_closed_trades_to_edge_proof_goal', 0) or 0)} | "
        f"regime={kpis.get('regime_dependency_state', 'not_available')} | "
        f"true_edge={float(kpis.get('true_edge_ratio', summary.get('true_edge_ratio')) or 0.0):.4f} | "
        f"decay={float(kpis.get('edge_decay_rate', summary.get('edge_decay_rate')) or 0.0):.4f}"
    )


def _edge_experiment_next_step(summary: dict[str, Any] | None) -> str | None:
    if not summary:
        return None
    posture = dict(summary.get("edge_proof_posture") or {})
    kpis = dict(summary.get("daily_edge_kpis") or {})
    proof_state = str(posture.get("state") or "unknown")
    proof_goal = max(int(summary.get("edge_proof_goal_closed_trades", 0) or 0), 0)
    remaining = max(int(summary.get("remaining_closed_trades_to_edge_proof_goal", 0) or 0), 0)
    if proof_state == "sample_building":
        return (
            "Advisory only: PAPER lineage is still in sample-building mode; treat split preferences as directional "
            f"while {remaining} closed trades remain to the {proof_goal}-close proof goal."
        )
    if proof_state == "regime_limited":
        return (
            "Advisory only: the edge proof goal is met, but regime dependency is still active; keep PAPER lineage "
            "running before treating the preferred branch as portable."
        )
    if proof_state == "proof_goal_met_but_edge_weak":
        return (
            "Advisory only: the proof goal is met, but current true-edge/decay still looks weak; keep PAPER-only "
            "until the edge stabilizes."
        )
    edge_state = str(summary.get("edge_state") or "")
    entry_timing = str(summary.get("entry_timing_preferred_variant") or "none")
    execution_style = str(summary.get("execution_style_preferred_variant") or "none")
    if edge_state == "fragile_edge":
        return (
            "Advisory only: fragile post-cost edge; keep PAPER lineage running but queue a controlled split review "
            f"for entry_timing={entry_timing} and execution_style={execution_style}."
        )
    if edge_state == "watch_edge":
        return (
            "Advisory only: unstable post-cost edge; compare PAPER outcomes against "
            f"entry_timing={entry_timing} and execution_style={execution_style} before changing the entry design."
        )
    if edge_state == "insufficient_edge_measurement":
        return "Advisory only: keep collecting closed PAPER samples before promoting edge experiment conclusions."
    return None


def _candidate_edge_experiment_focus(
    candidate: dict[str, Any] | None,
    edge_experiment_review: dict[str, Any] | None,
) -> dict[str, Any] | None:
    item = dict(candidate or {})
    if not item:
        return None
    row_focus = dict(item.get("edge_experiment_focus") or {})
    source = row_focus or dict(edge_experiment_review or {})
    if not source:
        return None
    return {
        "symbol": str(item.get("symbol") or ""),
        "strategy_family": str(item.get("strategy_family") or ""),
        "block_reason": str(item.get("block_reason") or ""),
        "edge_state": str(source.get("edge_state") or "insufficient_edge_measurement"),
        "entry_timing_preferred_variant": str(source.get("entry_timing_preferred_variant") or "none"),
        "execution_style_preferred_variant": str(source.get("execution_style_preferred_variant") or "none"),
        "true_edge_ratio": round(_float(source.get("true_edge_ratio")), 4),
        "focus_source": "row_level" if row_focus else "top_level_fallback",
    }


def _candidate_edge_experiment_focus_line(payload: dict[str, Any] | None) -> str:
    focus = dict(payload or {})
    if not focus:
        return "candidate_edge_focus: unavailable"
    line = (
        f"candidate_edge_focus: {focus.get('symbol') or 'unknown'} | "
        f"family={focus.get('strategy_family') or 'unknown'} | "
        f"edge={focus.get('edge_state') or 'insufficient_edge_measurement'} | "
        f"split={(focus.get('entry_timing_preferred_variant') or 'none')}/{(focus.get('execution_style_preferred_variant') or 'none')}"
    )
    if focus.get("block_reason"):
        line = f"{line} | reason={focus.get('block_reason')}"
    line = f"{line} | source={focus.get('focus_source') or 'unknown'}"
    return line


def _is_allowed_runtime_state(row: dict[str, Any], include_manual: bool) -> bool:
    state = str(row.get("deployment_go_no_go") or "").upper()
    if state == "GO":
        return True
    return include_manual and state == "MANUAL_REVIEW"


def _runtime_state_allows_override(row: dict[str, Any], include_manual: bool) -> bool:
    state = str(row.get("deployment_go_no_go") or "").upper()
    if not state:
        return True
    return _is_allowed_runtime_state(row, include_manual)


def _strategy_grade(row: dict[str, Any]) -> str:
    validity = dict(row.get("validity") or {})
    strategy_sizing = dict(row.get("strategy_sizing") or {})
    return str(
        row.get("strategy_grade")
        or validity.get("strategy_grade")
        or strategy_sizing.get("strategy_grade")
        or row.get("setup_grade")
        or ""
    ).upper()


def _rank_candidates(rows: list[dict[str, Any]], *, symbol: str | None, families: set[str], include_manual: bool) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        family = str(row.get("strategy_family") or "").lower()
        if family not in families:
            continue
        if symbol and str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        if not _is_allowed_runtime_state(row, include_manual):
            continue
        if float(row.get("recommended_risk_r") or 0.0) <= 0.0:
            continue
        filtered.append(row)
    if not filtered:
        return None
    filtered.sort(
        key=lambda row: (
            float(row.get("expected_ev_at_recommended_size_r") or 0.0),
            float(row.get("expected_ev_r") or 0.0),
            float(row.get("recommended_risk_r") or 0.0),
        ),
        reverse=True,
    )
    return filtered


def _choose_candidate(rows: list[dict[str, Any]], *, symbol: str | None, families: set[str], include_manual: bool) -> dict[str, Any] | None:
    ranked = _rank_candidates(rows, symbol=symbol, families=families, include_manual=include_manual)
    if not ranked:
        return None
    return ranked[0]


def _portfolio_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("accepted_candidates", "blocked_candidates"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    return rows


def _top_family_counts(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    counts = Counter(str(row.get("strategy_family") or "unknown") for row in rows if isinstance(row, dict))
    return [{"family": family, "count": count} for family, count in counts.most_common(limit)]


def _match_family_rows(rows: list[dict[str, Any]], families: set[str]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("strategy_family") or "").lower() in families]


def _family_availability_summary(
    *,
    scanner_rows: list[dict[str, Any]],
    portfolio_payload: dict[str, Any] | None,
    families: set[str],
) -> dict[str, Any]:
    portfolio = dict(portfolio_payload or {})
    accepted_rows = [dict(row) for row in (portfolio.get("accepted_candidates") or []) if isinstance(row, dict)]
    blocked_rows = [dict(row) for row in (portfolio.get("blocked_candidates") or []) if isinstance(row, dict)]
    alpha_rows = [dict(row) for row in (portfolio.get("alpha_research_candidates") or []) if isinstance(row, dict)]

    scanner_matches = _match_family_rows(scanner_rows, families)
    accepted_matches = _match_family_rows(accepted_rows, families)
    blocked_matches = _match_family_rows(blocked_rows, families)
    alpha_matches = _match_family_rows(alpha_rows, families)
    portfolio_match_count = len(accepted_matches) + len(blocked_matches) + len(alpha_matches)

    dominant_scanner = (_top_family_counts(scanner_rows, limit=1) or [{}])[0]
    dominant_blocked = (_top_family_counts(blocked_rows, limit=1) or [{}])[0]

    if len(scanner_rows) == 0 and portfolio_match_count == 0:
        availability_state = "scanner_surface_empty"
        summary = "Scanner returned zero rows for the current universe snapshot."
    elif len(scanner_matches) == 0 and portfolio_match_count == 0:
        availability_state = "requested_families_absent"
        summary = (
            f"No requested family candidate is present on the current surface; "
            f"scanner is dominated by `{dominant_scanner.get('family', 'unknown')}` "
            f"({int(dominant_scanner.get('count', 0) or 0)})."
        )
    else:
        availability_state = "requested_families_present_but_ineligible"
        summary = (
            f"Requested families are present but not currently eligible; "
            f"scanner_matches={len(scanner_matches)} portfolio_matches={portfolio_match_count}."
        )

    if dominant_blocked:
        summary = (
            f"{summary} Top blocked portfolio family is "
            f"`{dominant_blocked.get('family', 'unknown')}` "
            f"({int(dominant_blocked.get('count', 0) or 0)})."
        )

    return {
        "requested_families": sorted(families),
        "availability_state": availability_state,
        "summary": summary,
        "scanner_surface_count": len(scanner_rows),
        "scanner_match_count": len(scanner_matches),
        "portfolio_match_count": portfolio_match_count,
        "accepted_match_count": len(accepted_matches),
        "blocked_match_count": len(blocked_matches),
        "alpha_match_count": len(alpha_matches),
        "scanner_top_families": _top_family_counts(scanner_rows),
        "blocked_top_families": _top_family_counts(blocked_rows),
        "alpha_top_families": _top_family_counts(alpha_rows),
    }


def _rank_override_candidates(
    rows: list[dict[str, Any]],
    *,
    symbol: str | None,
    families: set[str],
    include_manual: bool,
) -> list[dict[str, Any]]:
    eligible_blocks = {"thesis_duplicate_blocked", "thesis_active_cap_reached"}
    filtered: list[dict[str, Any]] = []
    for row in rows:
        family = str(row.get("strategy_family") or "").lower()
        if family not in families:
            continue
        if symbol and str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        if not _runtime_state_allows_override(row, include_manual):
            continue
        if _strategy_grade(row) != "A":
            continue
        if str(row.get("block_reason") or "") not in eligible_blocks:
            continue
        filtered.append(row)
    if not filtered:
        return None
    filtered.sort(
        key=lambda row: (
            float(row.get("expected_ev_r") or 0.0),
            float(row.get("expected_ev_at_recommended_size_r") or 0.0),
            float(row.get("final_rank_score") or 0.0),
            float(row.get("recommended_risk_r") or 0.0),
        ),
        reverse=True,
    )
    return filtered


def _choose_override_candidate(
    rows: list[dict[str, Any]],
    *,
    symbol: str | None,
    families: set[str],
    include_manual: bool,
) -> dict[str, Any] | None:
    ranked = _rank_override_candidates(rows, symbol=symbol, families=families, include_manual=include_manual)
    if not ranked:
        return None
    return ranked[0]


def _skip_existing_sample_submit_block(intent: dict[str, Any] | None) -> bool:
    payload = dict(intent or {})
    submit_decision = str(payload.get("submit_decision") or "").strip().upper()
    reason_code = str(payload.get("decision_reason_code") or "").strip().lower()
    reason_message = str(payload.get("decision_reason_message") or "").strip().lower()
    if submit_decision == "SUBMIT":
        return False
    return (
        "duplicate_active_thesis" in reason_code
        or "plan_reentry_blocked" in reason_code
        or "skip_already_submitted" in submit_decision.lower()
        or "plan already has routed submission" in reason_message
        or "skip_existing_active_plan" in reason_code
        or "duplicate thesis detected against active plan" in reason_message
    )


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# PAPER Candidate Drill")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- overall_status: {payload['overall_status']}")
    lines.append(f"- summary: {payload['summary_line']}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for row in payload["checks"]:
        lines.append(f"- [{row['status']}] {row['name']}: {row['message']}")
    lines.append("")
    lines.append("## Approval Strip")
    lines.append("")
    approval_strip = payload.get("approval_strip_summary") or {}
    if approval_strip:
        lines.append(
            f"- approve={approval_strip.get('approve_value')} | "
            f"align={approval_strip.get('align_value')} | "
            f"act={approval_strip.get('act_value')} | "
            f"priority={approval_strip.get('act_priority_level')}"
        )
        lines.append(f"- reason: {approval_strip.get('primary_reason') or approval_strip.get('approve_reason')}")
    else:
        lines.append("- approval strip unavailable")
    lines.append("")
    lines.append("## Edge Experiment")
    lines.append("")
    edge_experiment = payload.get("edge_experiment_review") or {}
    if edge_experiment:
        lines.append(f"- {_edge_experiment_summary_line(edge_experiment)}")
        lines.append(f"- summary: {edge_experiment.get('summary', '')}")
    else:
        lines.append("- edge experiment unavailable")
    lines.append(f"- {_candidate_edge_experiment_focus_line(payload.get('candidate_edge_experiment_focus'))}")
    lines.append("")
    lines.append("## Candidate")
    lines.append("")
    candidate = payload.get("candidate") or {}
    if candidate:
        lines.append(f"- symbol: {candidate.get('symbol', '')}")
        lines.append(f"- plan_id: {candidate.get('plan_id', '')}")
        lines.append(f"- family: {candidate.get('strategy_family', '')}")
        lines.append(f"- candidate_surface: {candidate.get('deployment_go_no_go', '') or candidate.get('operator_status', '')}")
        lines.append(f"- expected_summary: {candidate.get('expected_summary', '')}")
    else:
        lines.append("- no eligible candidate found")
    family_availability = payload.get("family_availability_summary") or {}
    if family_availability:
        lines.append(f"- family_availability: {family_availability.get('availability_state', 'unknown')}")
        lines.append(f"- family_summary: {family_availability.get('summary', '')}")
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
    families = _family_set(args.families)

    sync_payload: dict[str, Any] | None = None
    if not args.skip_sync:
        sync_payload = _request_json(
            args.base_url,
            "POST",
            "/internal/binance/sync-universe",
            query={
                "limit_symbols": args.limit_symbols,
                "symbol_concurrency": args.symbol_concurrency,
                "limit_1m": args.limit_1m,
                "limit_5m": args.limit_5m,
                "limit_15m": args.limit_15m,
            },
        )

    scanner = _request_json(
        args.base_url,
        "GET",
        "/scanner/top",
        query={"universe": args.universe, "limit": args.candidate_limit},
    )
    scanner_rows = scanner if isinstance(scanner, list) else []
    candidate_pool = _rank_candidates(
        scanner_rows,
        symbol=args.symbol,
        families=families,
        include_manual=args.include_manual_review,
    )
    candidate = candidate_pool[0] if candidate_pool else None
    portfolio_payload: dict[str, Any] | None = None
    if candidate is None and args.paper_lineage_override:
        portfolio_raw = _request_json(
            args.base_url,
            "GET",
            "/portfolio/budget",
            query={"universe": args.universe, "limit": args.candidate_limit, "write_report": "false"},
        )
        portfolio_payload = portfolio_raw if isinstance(portfolio_raw, dict) else {}
        candidate_pool = _rank_override_candidates(
            _portfolio_candidates(portfolio_payload),
            symbol=args.symbol,
            families=families,
            include_manual=args.include_manual_review,
        )
        candidate = candidate_pool[0] if candidate_pool else None
    elif candidate is None:
        portfolio_raw = _request_json(
            args.base_url,
            "GET",
            "/portfolio/budget",
            query={"universe": args.universe, "limit": args.candidate_limit, "write_report": "false"},
        )
        portfolio_payload = portfolio_raw if isinstance(portfolio_raw, dict) else {}

    preview: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    intent: dict[str, Any] | None = None
    submission: dict[str, Any] | None = None
    validation_context: dict[str, Any] | None = None
    edge_experiment_review: dict[str, Any] | None = None
    symbol_refresh_summary: dict[str, Any] | None = None
    skipped_active_duplicate_candidates: list[dict[str, str]] = []
    if candidate is not None:
        for candidate_option in candidate_pool:
            validation_context = _request_json(
                args.base_url,
                "POST",
                "/validation/report",
                query={"symbol": str(candidate_option["symbol"])},
            )
            edge_experiment_review = _edge_experiment_summary(validation_context)
            preview_body = {
                "plan_id": candidate_option["plan_id"],
                "paper_lineage_override": bool(args.paper_lineage_override),
            }
            preview = _request_json(
                args.base_url,
                "POST",
                "/execution/plans/preview",
                body=preview_body,
            )
            approval = _request_json(
                args.base_url,
                "POST",
                "/execution/approve-plan",
                body=preview_body,
            )
            intent = _request_json(
                args.base_url,
                "POST",
                "/execution/order-intents",
                body={
                    "plan_id": candidate_option["plan_id"],
                    "execution_mode": "PAPER",
                    "paper_lineage_override": bool(args.paper_lineage_override),
                },
            )
            candidate = candidate_option
            if args.submit_paper and _skip_existing_sample_submit_block(intent):
                skipped_active_duplicate_candidates.append(
                    {
                        "symbol": str(candidate_option.get("symbol") or ""),
                        "plan_id": str(candidate_option.get("plan_id") or ""),
                        "reason_code": str(intent.get("decision_reason_code") or ""),
                    }
                )
                continue
            if args.submit_paper and str(intent.get("submit_decision") or "") == "SUBMIT":
                submission = _request_json(
                    args.base_url,
                    "POST",
                    "/execution/submit",
                    body={
                        "intent_id": intent["intent_id"],
                        "live": False,
                        "paper_scenario": args.paper_scenario,
                    },
                )
            break
    elif args.symbol:
        indicator_payload = _request_json(
            args.base_url,
            "GET",
            "/indicators/summary",
            query={"symbol": str(args.symbol), "refresh": "true", "plan_limit": 3, "zone_limit": 5},
        )
        if isinstance(indicator_payload, dict):
            symbol_refresh_summary = _symbol_refresh_summary(indicator_payload)
    candidate_edge_experiment_focus = _candidate_edge_experiment_focus(candidate, edge_experiment_review)
    candidate_surface_summary = _scanner_candidate_strip_summary(candidate)
    approval_strip_summary = _approval_strip_summary(approval) or candidate_surface_summary
    family_availability_summary = _family_availability_summary(
        scanner_rows=scanner_rows,
        portfolio_payload=portfolio_payload,
        families=families,
    )

    checks: list[dict[str, str]] = []
    if sync_payload is not None:
        checks.append(
            {
                "name": "universe_sync",
                "status": _status(int(sync_payload.get("success", 0) or 0) > 0 or int(sync_payload.get("processed_symbols", 0) or 0) > 0),
                "message": f"success={sync_payload.get('success', 0)} failed={sync_payload.get('failed', 0)} processed={sync_payload.get('processed_symbols', 0)}",
            }
        )
    checks.append(
        {
            "name": "eligible_candidate_found",
            "status": _status(candidate is not None),
            "message": (
                (
                    "No eligible trend_continuation/sweep_reversal candidate found in scanner output."
                    + (
                        f" {symbol_refresh_summary.get('message', '')}"
                        if symbol_refresh_summary and str(symbol_refresh_summary.get("message") or "")
                        else ""
                    )
                )
                if candidate is None
                else (
                    f"{candidate.get('symbol')} {candidate.get('strategy_family')} "
                    f"approve={(candidate_surface_summary or {}).get('approve_value', candidate.get('deployment_go_no_go', ''))} | "
                    f"act={(candidate_surface_summary or {}).get('act_value', 'continue_candidate_review_under_portfolio_caps')}"
                    + (
                        " via paper lineage override"
                        if bool(args.paper_lineage_override)
                        and str(candidate.get("block_reason") or "") in {"thesis_duplicate_blocked", "thesis_active_cap_reached"}
                        else ""
                    )
                )
            ),
        }
    )
    if candidate is not None:
        checks.append(
            {
                "name": "preview_ready",
                "status": _status(preview is not None),
                "message": f"entry_type={preview.get('entry_type', '')} semantics={preview.get('entry_semantics', '')}" if preview else "preview unavailable",
            }
        )
        approval_state = str((approval or {}).get("approval_state") or "")
        allowed_execution_mode = str((approval or {}).get("allowed_execution_mode") or "")
        checks.append(
            {
                "name": "approval_for_paper",
                "status": _status(approval_state in {"APPROVED_AUTO", "APPROVED_MANUAL"} and allowed_execution_mode in {"PAPER", "MICRO_LIVE", "LIVE"}),
                "message": (
                    f"approve={(approval_strip_summary or {}).get('approve_value', approval_state)} | "
                    f"align={(approval_strip_summary or {}).get('align_value', 'aligned')} | "
                    f"act={(approval_strip_summary or {}).get('act_value', '')} | "
                    f"approval_state={approval_state} allowed_execution_mode={allowed_execution_mode}"
                    + (
                        f" override={approval.get('paper_lineage_override_reason', '')}"
                        if approval and approval.get("paper_lineage_override_applied")
                        else ""
                    )
                ),
            }
        )
        submit_decision = str((intent or {}).get("submit_decision") or "")
        checks.append(
            {
                "name": "intent_submit_ready",
                "status": _status(submit_decision == "SUBMIT"),
                "message": f"submit_decision={submit_decision or 'unknown'} reason={(intent or {}).get('decision_reason_code', '')}",
            }
        )
        if args.submit_paper:
            checks.append(
                {
                    "name": "paper_submit",
                    "status": _status(submission is not None and str(submission.get('submit_status') or "") in {"FILLED", "ACKNOWLEDGED", "PARTIALLY_FILLED"}),
                    "message": (
                        "paper submit not attempted"
                        if submission is None
                        else f"submit_status={submission.get('submit_status', '')} state={submission.get('state', '')}"
                    ),
                }
            )

    fail_count = sum(1 for row in checks if row["status"] == "FAIL")
    overall_status = "READY_FOR_PAPER_SAMPLE" if fail_count == 0 else "NOT_READY"

    next_steps: list[str] = []
    if candidate is None:
        next_steps.append("Wait for London/New York session and rerun this helper until an eligible family candidate appears.")
        next_steps.append("Keep focus on trend_continuation or sweep_reversal families; legacy_zone_plan does not advance MICRO_LIVE lineage.")
        if family_availability_summary.get("availability_state") == "scanner_surface_empty":
            next_steps.append("Scanner returned zero rows for this universe snapshot; treat this as a surface-empty wait and recheck the next session window.")
        elif family_availability_summary.get("availability_state") == "requested_families_absent":
            next_steps.append("Requested PAPER lineage families are absent from both scanner and portfolio surfaces; this is a market-availability wait, not an approval blockage.")
        else:
            next_steps.append("Requested PAPER lineage families are present but not eligible; inspect portfolio block reasons before widening scope.")
        if symbol_refresh_summary and str(symbol_refresh_summary.get("message") or ""):
            next_steps.append(str(symbol_refresh_summary["message"]))
    else:
        if intent is not None and str(intent.get("submit_decision") or "") != "SUBMIT":
            next_steps.append(f"Candidate found but PAPER intent is not submit-ready: {(intent or {}).get('decision_reason_message', '')}")
        elif not args.submit_paper:
            next_steps.append("Rerun with --submit-paper to create a PAPER submission once the candidate looks acceptable.")
        elif submission is not None:
            next_steps.append("Monitor execution/operator-dashboard and validation/report after the PAPER submission closes.")
            next_steps.append("Repeat this drill until enough closed v2 trades exist to resolve threshold lineage winner.")
        if skipped_active_duplicate_candidates:
            skipped_symbols = ", ".join(
                f"{item.get('symbol') or 'unknown'}[{item.get('reason_code') or 'duplicate'}]"
                for item in skipped_active_duplicate_candidates
            )
            next_steps.append(f"Skipped active-sample duplicates while searching for a new PAPER lineage candidate: {skipped_symbols}.")
    advisory_next_step = _edge_experiment_next_step(edge_experiment_review)
    if advisory_next_step:
        next_steps.append(advisory_next_step)
    if submission is None and args.submit_paper:
        next_steps.append("No PAPER submission occurred in this run.")

    payload = {
        "generated_at": generated_at.isoformat(),
        "symbol": (args.symbol or "").upper() or None,
        "universe": args.universe,
        "families": sorted(families),
        "paper_lineage_override": bool(args.paper_lineage_override),
        "overall_status": overall_status,
        "summary_line": (
            "Eligible PAPER candidate is ready."
            if overall_status == "READY_FOR_PAPER_SAMPLE"
            else f"{fail_count} blocking drill check(s) remain."
        ),
        "checks": checks,
        "sync": sync_payload,
        "portfolio": portfolio_payload,
        "candidate": candidate,
        "candidate_surface_summary": candidate_surface_summary,
        "family_availability_summary": family_availability_summary,
        "symbol_refresh_summary": symbol_refresh_summary,
        "validation_context": validation_context,
        "preview": preview,
        "approval": approval,
        "approval_strip_summary": approval_strip_summary,
        "edge_experiment_review": edge_experiment_review,
        "candidate_edge_experiment_focus": candidate_edge_experiment_focus,
        "intent": intent,
        "submission": submission,
        "next_steps": next_steps,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        symbol_tag = (candidate or {}).get("symbol") or (args.symbol or "UNIVERSE").upper()
        report_path = ROOT_DIR / args.report_dir / f"paper_candidate_drill_{symbol_tag}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if overall_status == "READY_FOR_PAPER_SAMPLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
