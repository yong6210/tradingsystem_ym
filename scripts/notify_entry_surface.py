#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from http.client import RemoteDisconnected
from pathlib import Path
import socket
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.live_route_contract import (
    attach_live_route_status,
    live_route_contract_from_settings,
)
from app.services.notification_dispatcher import NotificationDispatcher
from scripts.operation_report_io import atomic_write_text


ACTIONABLE_ENTRY = "ACTIONABLE_ENTRY"
LIVE_ORDER_CANDIDATE = "LIVE_ORDER_CANDIDATE"
CONTEXT_REVIEW_SETUP = "CONTEXT_REVIEW_SETUP"
BLOCKED_SETUP = "BLOCKED_SETUP"
RESEARCH_ONLY_SETUP = "RESEARCH_ONLY_SETUP"
SURFACE_STATUSES = (LIVE_ORDER_CANDIDATE, CONTEXT_REVIEW_SETUP, BLOCKED_SETUP, RESEARCH_ONLY_SETUP)
ALERT_STATUSES = SURFACE_STATUSES
_REQUEST_RETRY_ATTEMPTS = 2
_REQUEST_RETRY_BASE_DELAY_SECONDS = 1.0
_REQUEST_TIMEOUT_SECONDS = 60
_DEFAULT_REPEAT_SUPPRESSION_MINUTES = 360
_REROUTE_SUFFIX_RE = re.compile(r"_r[0-9a-f]{4,}$", re.IGNORECASE)


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


def _default_lock_file(state_file: Path) -> Path:
    return state_file.with_name(f"{state_file.name}.lock")


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
    parser.add_argument("--output-file", default="")
    parser.add_argument("--webhook-url", default="")
    parser.add_argument("--lock-file", default="")
    parser.add_argument(
        "--min-repeat-minutes",
        type=int,
        default=_DEFAULT_REPEAT_SUPPRESSION_MINUTES,
        help=(
            "Suppress a recently notified stable surface state for this many minutes, even if the previous "
            "run observed a different transient state."
        ),
    )
    parser.add_argument("--force-send", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Write output artifacts without printing JSON to stdout.")
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
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _emit_result(path: Path | None, payload: dict[str, Any], *, quiet: bool = False) -> None:
    if path is not None:
        _write_json(path, payload)
    if not quiet:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def _ensure_http_url(url: str) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"unsupported request URL scheme: {scheme or 'missing'}")


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
    _ensure_http_url(url)
    last_error: RuntimeError | None = None
    for attempt in range(1, _REQUEST_RETRY_ATTEMPTS + 1):
        request = Request(url=url, headers={"Accept": "application/json"}, method=method.upper())  # noqa: S310
        try:
            with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
                break
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code >= 500 or "database is locked" in body.lower() or "sqlite busy" in body.lower()
            last_error = RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {body}")
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
    else:
        raise last_error or RuntimeError(f"{method.upper()} {path} failed without an exception payload")

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


def _live_route_contract_from_settings(settings: Any) -> dict[str, Any]:
    return live_route_contract_from_settings(settings)


def _attach_live_route_status(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    return attach_live_route_status(row, contract)


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
        "available": _safe_bool(summary.get("available", True), default=True),
        "advisory_only": _safe_bool(summary.get("advisory_only", True), default=True),
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
        "available": _safe_bool(summary.get("available", True), default=True),
        "advisory_only": _safe_bool(summary.get("advisory_only", True), default=True),
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
        "available": _safe_bool(summary.get("available", False)),
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


def _sorted_counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _route_mismatch_summary(sections: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    context_rows: list[dict[str, Any]] = []
    covered_statuses = (CONTEXT_REVIEW_SETUP, BLOCKED_SETUP)
    for status in covered_statuses:
        for row in list(sections.get(status) or []):
            route = dict(row.get("entry_surface_route") or {})
            if _safe_bool(route.get("live_routable")) or _safe_bool(row.get("live_routable")):
                continue
            context_rows.append(row)

    reasons: list[str] = []
    families: list[str] = []
    entry_models: list[str] = []
    symbols: list[str] = []
    status_counts: list[str] = []
    missing_reason_count = 0
    for row in context_rows:
        route = dict(row.get("entry_surface_route") or {})
        route_reasons = [
            str(reason or "").strip()
            for reason in list(route.get("reasons") or [])
            if str(reason or "").strip()
        ]
        if route_reasons:
            reasons.extend(route_reasons)
        else:
            missing_reason_count += 1
        family = str(route.get("strategy_family") or _candidate_family(row) or "unknown").strip().lower()
        entry_model = str(route.get("entry_model") or row.get("entry_model") or "unknown").strip().upper()
        symbol = str(route.get("symbol") or row.get("symbol") or "UNKNOWN").strip().upper()
        families.append(family or "unknown")
        entry_models.append(entry_model or "UNKNOWN")
        symbols.append(symbol or "UNKNOWN")
        status_counts.append(str(route.get("status") or "context_only").strip() or "context_only")

    return {
        "covered_statuses": list(covered_statuses),
        "context_only_total": len(context_rows),
        "missing_reason_count": missing_reason_count,
        "by_reason": _sorted_counts(reasons),
        "by_strategy_family": _sorted_counts(families),
        "by_entry_model": _sorted_counts(entry_models),
        "by_symbol": _sorted_counts(symbols),
        "by_route_status": _sorted_counts(status_counts),
    }


def _top_count_item(raw_counts: Any) -> str:
    counts = dict(raw_counts or {}) if isinstance(raw_counts, dict) else {}
    for key, value in counts.items():
        return f"{key}:{int(value or 0)}"
    return "none"


def _entry_surface_operator_action(snapshot: dict[str, Any]) -> dict[str, Any]:
    counts = dict(snapshot.get("counts") or {})
    route_summary = dict(snapshot.get("route_mismatch_summary") or {})
    blocked_breakdown = _blocked_route_breakdown(snapshot)
    live_count = int(counts.get(LIVE_ORDER_CANDIDATE, 0) or 0)
    blocked_live_count = int(blocked_breakdown.get("live_routable", 0) or 0)
    blocked_context_count = int(blocked_breakdown.get("context_only", 0) or 0)
    context_review_count = int(counts.get(CONTEXT_REVIEW_SETUP, 0) or 0)
    context_only_total = int(route_summary.get("context_only_total", 0) or 0)

    if live_count > 0:
        state = "live_order_candidate_present"
        priority = "important"
        next_action = "review_live_order_candidate_intent_submission"
        message = "LIVE_ORDER_CANDIDATE가 있어 intent/submission/fill 경로를 확인할 상태"
    elif blocked_live_count > 0:
        state = "live_order_candidate_blocked"
        priority = "watch"
        next_action = "inspect_validation_portfolio_risk_blockers"
        message = "live route에 맞는 후보가 있었지만 validation/portfolio/risk에서 주문 전 차단된 상태"
    elif context_only_total > 0 or context_review_count > 0 or blocked_context_count > 0:
        state = "context_only_outside_live_route"
        priority = "monitor"
        next_action = "wait_for_live_route_candidate_or_change_live_contract_intentionally"
        message = "surface 활동은 있지만 현재 live route 밖이라 주문을 기대하지 않는 상태"
    else:
        state = "no_surface_candidates"
        priority = "monitor"
        next_action = "wait_for_fresh_live_candidate"
        message = "현재 surface에 주문/검토/차단 후보가 없어 fresh 후보를 기다리는 상태"

    return {
        "state": state,
        "priority": priority,
        "next_action": next_action,
        "message": message,
        "live_order_candidates": live_count,
        "blocked_live_order_candidates": blocked_live_count,
        "blocked_context_only_setups": blocked_context_count,
        "context_review_setups": context_review_count,
        "route_mismatch_total": context_only_total,
        "top_route_mismatch_reason": _top_count_item(route_summary.get("by_reason")),
        "top_route_mismatch_family": _top_count_item(route_summary.get("by_strategy_family")),
        "top_route_mismatch_entry_model": _top_count_item(route_summary.get("by_entry_model")),
        "top_route_mismatch_symbol": _top_count_item(route_summary.get("by_symbol")),
    }


def build_entry_snapshot(
    payload: dict[str, Any],
    *,
    symbol: str = "",
    max_per_status: int = 3,
    live_route_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = dict(live_route_contract or _live_route_contract_from_settings(get_settings()))
    accepted_rows = [
        _attach_live_route_status(row, contract) for row in _filter_rows(payload.get("accepted_candidates"), symbol=symbol)
    ]
    blocked_rows = [
        _attach_live_route_status(row, contract) for row in _filter_rows(payload.get("blocked_candidates"), symbol=symbol)
    ]
    research_rows = [
        _attach_live_route_status(row, contract)
        for row in _filter_rows(payload.get("alpha_research_candidates"), symbol=symbol)
    ]

    research_plan_ids = {str(row.get("plan_id") or "") for row in research_rows}
    blocked_non_research_all = [row for row in blocked_rows if str(row.get("plan_id") or "") not in research_plan_ids]

    deployment_state = str(payload.get("deployment_go_no_go") or "MANUAL_REVIEW").upper()
    live_order_rows_all: list[dict[str, Any]] = []
    context_review_rows_all: list[dict[str, Any]] = []
    if deployment_state == "GO":
        for row in accepted_rows:
            route = dict(row.get("entry_surface_route") or {})
            if _safe_bool(route.get("live_routable")):
                live_order_rows_all.append(row)
            else:
                context_review_rows_all.append(row)
    else:
        reason_code, reason_message = _blocked_topline_reason(payload)
        for row in accepted_rows:
            shadow = dict(row)
            shadow["block_reason"] = shadow.get("block_reason") or reason_code
            shadow["block_reason_message"] = shadow.get("block_reason_message") or reason_message
            blocked_non_research_all.append(shadow)

    live_order_rows_all = sorted(live_order_rows_all, key=_sort_actionable_key, reverse=True)
    context_review_rows_all = sorted(context_review_rows_all, key=_sort_actionable_key, reverse=True)
    blocked_non_research_all = sorted(blocked_non_research_all, key=_sort_blocked_key, reverse=True)
    research_rows_all = sorted(research_rows, key=_sort_research_key, reverse=True)
    source_sections = {
        LIVE_ORDER_CANDIDATE: live_order_rows_all,
        CONTEXT_REVIEW_SETUP: context_review_rows_all,
        BLOCKED_SETUP: blocked_non_research_all,
        RESEARCH_ONLY_SETUP: research_rows_all,
    }
    max_rows = max(0, int(max_per_status))
    sections = {status: rows[:max_rows] for status, rows in source_sections.items()}
    counts = {status: len(rows) for status, rows in source_sections.items()}
    display_counts = {status: len(rows) for status, rows in sections.items()}
    truncated_counts = {
        status: max(0, counts.get(status, 0) - display_counts.get(status, 0)) for status in SURFACE_STATUSES
    }

    snapshot = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": _candidate_scope(payload, symbol),
        "live_route_contract": {
            "authority": str(contract.get("authority") or "live_candidate_promotion_readiness_is_order_truth"),
            "execution_mode": str(contract.get("execution_mode") or ""),
            "symbols": list(contract.get("symbols") or []),
            "strategy_families": list(contract.get("strategy_families") or []),
            "entry_models": list(contract.get("entry_models") or []),
            "sessions": list(contract.get("sessions") or []),
            "direction_contract": dict(contract.get("direction_contract") or {}),
        },
        "deployment_go_no_go": deployment_state,
        "deployment_code": str(payload.get("deployment_code") or ""),
        "deployment_message": str(payload.get("deployment_message") or ""),
        "playbook_go_no_go": str(payload.get("playbook_go_no_go") or ""),
        "playbook_action": str(payload.get("playbook_action") or ""),
        "approval_strip": _approval_strip_summary(payload),
        "edge_experiment_review": _edge_experiment_summary(payload),
        "edge_evolution_rule": _edge_evolution_summary(payload),
        "review_followup_ledger": _review_followup_summary(payload),
        "counts": counts,
        "source_counts": counts,
        "display_counts": display_counts,
        "truncated_counts": truncated_counts,
        "section_limit": max_rows,
        "blocked_setup_breakdown": _blocked_route_breakdown_from_rows(blocked_non_research_all),
        "route_mismatch_summary": _route_mismatch_summary(source_sections),
        "sections": sections,
    }
    snapshot["operator_action_summary"] = _entry_surface_operator_action(snapshot)
    return snapshot


def build_alert_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    sections = dict(snapshot.get("sections") or {})
    approval_strip = dict(snapshot.get("approval_strip") or {})
    edge_experiment = dict(snapshot.get("edge_experiment_review") or {})
    edge_evolution = dict(snapshot.get("edge_evolution_rule") or {})
    review_followup = dict(snapshot.get("review_followup_ledger") or {})
    live_contract = dict(snapshot.get("live_route_contract") or {})
    return {
        "scope": str(snapshot.get("scope") or ""),
        "live_route_contract": {
            "execution_mode": str(live_contract.get("execution_mode") or ""),
            "symbols": sorted(str(item or "").strip().upper() for item in list(live_contract.get("symbols") or [])),
            "strategy_families": sorted(
                str(item or "").strip().lower() for item in list(live_contract.get("strategy_families") or [])
            ),
            "entry_models": sorted(
                str(item or "").strip().upper() for item in list(live_contract.get("entry_models") or [])
            ),
            "sessions": sorted(str(item or "").strip().lower() for item in list(live_contract.get("sessions") or [])),
            "direction_contract": {
                str(symbol or "").strip().upper(): sorted(
                    str(direction or "").strip().upper() for direction in list(directions or [])
                )
                for symbol, directions in dict(live_contract.get("direction_contract") or {}).items()
            },
        },
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
            status: int((snapshot.get("counts") or {}).get(status, 0) or 0) for status in ALERT_STATUSES
        },
        "sections": {
            status: [_row_alert_identity(status, row) for row in sections.get(status) or []] for status in ALERT_STATUSES
        },
    }


def _stable_plan_id(raw_plan_id: Any) -> str:
    return _REROUTE_SUFFIX_RE.sub("", str(raw_plan_id or "").strip())


def _row_alert_identity(status: str, row: dict[str, Any]) -> dict[str, Any]:
    edge_focus = dict(row.get("edge_experiment_focus") or {})
    route = dict(row.get("entry_surface_route") or {})
    route_reasons = [str(reason or "") for reason in list(route.get("reasons") or []) if str(reason or "")]
    payload = {
        "symbol": str(row.get("symbol") or ""),
        "stable_plan_id": _stable_plan_id(row.get("plan_id")),
        "direction": str(row.get("direction") or "").lower(),
        "entry_model": str(row.get("entry_model") or "").upper(),
        "family": _candidate_family(row),
        "route_status": str(route.get("status") or ""),
        "live_routable": bool(route.get("live_routable")),
        "route_reasons": route_reasons,
        "session_name": str(route.get("session_name") or ""),
        "edge_state": str(edge_focus.get("edge_state") or ""),
        "entry_timing_focus": str(edge_focus.get("entry_timing_preferred_variant") or ""),
        "execution_style_focus": str(edge_focus.get("execution_style_preferred_variant") or ""),
    }
    if status == CONTEXT_REVIEW_SETUP:
        payload["reason_code"] = ",".join(route_reasons) or "outside_live_route"
    elif status == BLOCKED_SETUP:
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


def _alert_state_signature(alert_state: dict[str, Any]) -> str:
    raw = json.dumps(alert_state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _extract_alert_state_history(payload: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    raw_history = payload.get("alert_state_history")
    if not isinstance(raw_history, dict):
        return {}
    history: dict[str, str] = {}
    for key, value in raw_history.items():
        signature = str(key or "").strip()
        timestamp = str(value or "").strip()
        if signature and timestamp:
            history[signature] = timestamp
    return history


def _parse_utc_timestamp(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _recent_history_match(
    history: dict[str, str],
    *,
    signature: str,
    now: datetime,
    min_repeat_minutes: int,
) -> tuple[bool, str]:
    if min_repeat_minutes <= 0:
        return (False, "")
    last_raw = str(history.get(signature) or "")
    last_seen = _parse_utc_timestamp(last_raw)
    if last_seen is None:
        return (False, "")
    return (now - last_seen < timedelta(minutes=min_repeat_minutes), last_seen.isoformat())


def _updated_alert_state_history(
    history: dict[str, str],
    *,
    signature: str,
    now: datetime,
    max_items: int = 64,
) -> dict[str, str]:
    updated = dict(history)
    updated[signature] = now.isoformat()
    sortable: list[tuple[datetime, str, str]] = []
    for key, value in updated.items():
        parsed = _parse_utc_timestamp(value) or datetime.min.replace(tzinfo=UTC)
        sortable.append((parsed, key, value))
    sortable.sort(reverse=True)
    return {key: value for _, key, value in sortable[:max_items]}


def _format_candidate_line(status: str, row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "UNKNOWN")
    direction = str(row.get("direction") or "").lower() or "unknown"
    entry_model = str(row.get("entry_model") or "").upper() or "UNKNOWN"
    family = _candidate_family(row)
    risk_r = float(row.get("recommended_risk_r", 0.0) or 0.0)
    expected_summary = str(row.get("expected_summary") or "").strip()
    route = dict(row.get("entry_surface_route") or {})
    live_routable = _safe_bool(route.get("live_routable"))
    route_reasons = [str(reason or "") for reason in list(route.get("reasons") or []) if str(reason or "")]

    parts = [
        f"{symbol} {direction} {entry_model}",
        f"family={family}",
        f"live_routable={'true' if live_routable else 'false'}",
    ]
    if route_reasons:
        parts.append(f"route_reasons={','.join(route_reasons)}")
    parts.append(f"risk={risk_r:.2f}R")
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


def _section_title(status: str) -> str:
    labels = {
        LIVE_ORDER_CANDIDATE: "[주문 후보] LIVE_ORDER_CANDIDATE",
        CONTEXT_REVIEW_SETUP: "[검토 후보] CONTEXT_REVIEW_SETUP",
        BLOCKED_SETUP: "[차단 후보] BLOCKED_SETUP",
        RESEARCH_ONLY_SETUP: "[연구 후보] RESEARCH_ONLY_SETUP",
    }
    return labels.get(status, status)


def _format_contract_trace(snapshot: dict[str, Any]) -> str:
    approval_strip = dict(snapshot.get("approval_strip") or {})
    return (
        f"contract_trace: approve={approval_strip.get('approve_value')} "
        f"| align={approval_strip.get('align_value')} "
        f"| act={approval_strip.get('act_value')} "
        f"| runtime={snapshot.get('deployment_go_no_go')}/{snapshot.get('deployment_code')} "
        f"| playbook={snapshot.get('playbook_go_no_go')}"
    )


def _format_live_route_trace(snapshot: dict[str, Any]) -> str:
    counts = dict(snapshot.get("counts") or {})
    contract = dict(snapshot.get("live_route_contract") or {})
    symbols = list(contract.get("symbols") or [])
    families = list(contract.get("strategy_families") or [])
    entry_models = list(contract.get("entry_models") or [])
    sessions = list(contract.get("sessions") or [])
    direction_contract = dict(contract.get("direction_contract") or {})
    return (
        "order_route_truth: authority=live_candidate_promotion_readiness "
        f"| live_order_candidates={int(counts.get(LIVE_ORDER_CANDIDATE, 0) or 0)} "
        f"| blocked_live_candidates={_blocked_live_candidate_count(snapshot)} "
        f"| review_only_candidates={int(counts.get(CONTEXT_REVIEW_SETUP, 0) or 0)} "
        f"| mode={contract.get('execution_mode') or 'UNKNOWN'} "
        f"| symbols={','.join(str(item) for item in symbols) or 'none'} "
        f"| families={','.join(str(item) for item in families) or 'none'} "
        f"| entry_models={','.join(str(item) for item in entry_models) or 'any'} "
        f"| sessions={','.join(str(item) for item in sessions) or 'any'} "
        f"| direction_contract_symbols={len(direction_contract)}"
    )


def _format_count_map(raw_counts: Any, *, limit: int = 4) -> str:
    counts = dict(raw_counts or {}) if isinstance(raw_counts, dict) else {}
    parts: list[str] = []
    for index, (key, value) in enumerate(counts.items()):
        if index >= max(0, int(limit)):
            break
        parts.append(f"{key}:{int(value or 0)}")
    return ",".join(parts) if parts else "none"


def _format_route_mismatch_trace(snapshot: dict[str, Any]) -> str:
    summary = dict(snapshot.get("route_mismatch_summary") or {})
    return (
        "route_mismatch: "
        f"context_only={int(summary.get('context_only_total', 0) or 0)} "
        f"| reasons={_format_count_map(summary.get('by_reason'))} "
        f"| families={_format_count_map(summary.get('by_strategy_family'))} "
        f"| entry_models={_format_count_map(summary.get('by_entry_model'))} "
        f"| symbols={_format_count_map(summary.get('by_symbol'))}"
    )


def _format_operator_action_trace(snapshot: dict[str, Any]) -> str:
    action = dict(snapshot.get("operator_action_summary") or _entry_surface_operator_action(snapshot))
    return (
        "operator_action: "
        f"state={action.get('state') or 'unknown'} "
        f"| priority={action.get('priority') or 'monitor'} "
        f"| next={action.get('next_action') or 'wait_for_fresh_live_candidate'} "
        f"| reason={action.get('top_route_mismatch_reason') or 'none'} "
        f"| family={action.get('top_route_mismatch_family') or 'none'} "
        f"| entry_model={action.get('top_route_mismatch_entry_model') or 'none'} "
        f"| symbol={action.get('top_route_mismatch_symbol') or 'none'}"
    )


def _format_edge_experiment_trace(snapshot: dict[str, Any]) -> str:
    edge_experiment = dict(snapshot.get("edge_experiment_review") or {})
    if not edge_experiment:
        return "live_validation: unavailable"
    focus = str(edge_experiment.get("focus_symbol") or "")
    focus_status = str(edge_experiment.get("focus_status") or "")
    focus_suffix = f" | focus={focus}/{focus_status}" if focus and focus_status else ""
    posture = dict(edge_experiment.get("edge_proof_posture") or {})
    kpis = dict(edge_experiment.get("daily_edge_kpis") or {})
    return (
        f"live_validation: state={edge_experiment.get('edge_state')} "
        f"| entry_timing={edge_experiment.get('entry_timing_preferred_variant')} "
        f"| execution_style={edge_experiment.get('execution_style_preferred_variant')} "
        f"| validation={posture.get('state', 'unknown')}/{posture.get('claim_state', 'unknown')} "
        f"| closed={int(kpis.get('closed_trade_count', 0) or 0)}/{int(edge_experiment.get('edge_proof_goal_closed_trades', 0) or 0)} "
        f"| remaining_to_goal={int(edge_experiment.get('remaining_closed_trades_to_edge_proof_goal', 0) or 0)} "
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
    display_counts = dict(snapshot.get("display_counts") or counts)
    truncated_counts = dict(snapshot.get("truncated_counts") or {})
    sections = dict(snapshot.get("sections") or {})
    approval_strip = dict(snapshot.get("approval_strip") or {})
    live_count = int(counts.get(LIVE_ORDER_CANDIDATE, 0) or 0)
    review_count = int(counts.get(CONTEXT_REVIEW_SETUP, 0) or 0)
    blocked_breakdown = _blocked_route_breakdown(snapshot)
    blocked_live_count = int(blocked_breakdown.get("live_routable", 0) or 0)
    blocked_context_count = int(blocked_breakdown.get("context_only", 0) or 0)
    lines = [
        (
            "Trading entry surface alert: "
            f"live_order_candidates={live_count}, review_candidates={review_count}, "
            f"blocked_live_candidates={blocked_live_count}, "
            f"blocked_context_only={blocked_context_count}"
        ),
        f"scope: {snapshot.get('scope')} | order_truth=live_candidate_promotion_readiness",
        (
            f"approval_strip: approve={approval_strip.get('approve_value')} "
            f"| align={approval_strip.get('align_value')} "
            f"| act={approval_strip.get('act_value')} "
            f"| priority={approval_strip.get('act_priority_level')}"
        ),
        f"reason: {approval_strip.get('primary_reason') or snapshot.get('deployment_message')}",
        _format_contract_trace(snapshot),
        _format_live_route_trace(snapshot),
        _format_route_mismatch_trace(snapshot),
        _format_operator_action_trace(snapshot),
        _format_edge_experiment_trace(snapshot),
        _format_edge_evolution_trace(snapshot),
        _format_review_followup_trace(snapshot),
        (
            f"counts: {LIVE_ORDER_CANDIDATE}={counts.get(LIVE_ORDER_CANDIDATE, 0)}, "
            f"{CONTEXT_REVIEW_SETUP}={counts.get(CONTEXT_REVIEW_SETUP, 0)}, "
            f"{BLOCKED_SETUP}={counts.get(BLOCKED_SETUP, 0)}, "
            f"{RESEARCH_ONLY_SETUP}={counts.get(RESEARCH_ONLY_SETUP, 0)} "
            f"| displayed={LIVE_ORDER_CANDIDATE}:{display_counts.get(LIVE_ORDER_CANDIDATE, 0)},"
            f"{CONTEXT_REVIEW_SETUP}:{display_counts.get(CONTEXT_REVIEW_SETUP, 0)},"
            f"{BLOCKED_SETUP}:{display_counts.get(BLOCKED_SETUP, 0)},"
            f"{RESEARCH_ONLY_SETUP}:{display_counts.get(RESEARCH_ONLY_SETUP, 0)} "
            f"| truncated={LIVE_ORDER_CANDIDATE}:{truncated_counts.get(LIVE_ORDER_CANDIDATE, 0)},"
            f"{CONTEXT_REVIEW_SETUP}:{truncated_counts.get(CONTEXT_REVIEW_SETUP, 0)},"
            f"{BLOCKED_SETUP}:{truncated_counts.get(BLOCKED_SETUP, 0)},"
            f"{RESEARCH_ONLY_SETUP}:{truncated_counts.get(RESEARCH_ONLY_SETUP, 0)} "
            f"| blocked_breakdown=live:{blocked_live_count},context_only:{blocked_context_count}"
        ),
    ]

    for status in SURFACE_STATUSES:
        rows = sections.get(status) or []
        lines.append("")
        section_title = _section_title(status)
        total_count = int(counts.get(status, 0) or 0)
        display_count = int(display_counts.get(status, len(rows)) or 0)
        if total_count > display_count:
            section_title = f"{section_title} (showing={display_count}/{total_count})"
        if status == BLOCKED_SETUP:
            section_title = f"{section_title} (live={blocked_live_count}, context_only={blocked_context_count})"
        lines.append(section_title)
        if not rows:
            lines.append("- none")
            continue
        lines.extend(_format_candidate_line(status, row) for row in rows)
    return "\n".join(lines)


def _has_alertable_rows(snapshot: dict[str, Any]) -> bool:
    counts = dict(snapshot.get("counts") or {})
    if int(counts.get(LIVE_ORDER_CANDIDATE, 0) or 0) > 0:
        return True
    return _blocked_live_candidate_count(snapshot) > 0


def _no_alertable_reason(snapshot: dict[str, Any]) -> str:
    action = dict(snapshot.get("operator_action_summary") or _entry_surface_operator_action(snapshot))
    state = str(action.get("state") or "").strip()
    if state == "context_only_outside_live_route":
        return "no_live_order_candidates_context_only_route_mismatch"
    if state == "no_surface_candidates":
        return "no_surface_candidates"
    return "no_alertable_rows"


def _result_status_fields(snapshot: dict[str, Any]) -> dict[str, str]:
    action = dict(snapshot.get("operator_action_summary") or _entry_surface_operator_action(snapshot))
    state = str(action.get("state") or "").strip()
    status = "WATCH" if _has_alertable_rows(snapshot) else "PASS"
    return {
        "status": status,
        "overall_status": status,
        "status_detail": f"entry_surface_{state}" if state else f"entry_surface_{status.lower()}",
    }


def _blocked_live_candidate_count(snapshot: dict[str, Any]) -> int:
    return int(_blocked_route_breakdown(snapshot).get("live_routable", 0) or 0)


def _blocked_route_breakdown_from_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    live_routable = 0
    context_only = 0
    for row in rows:
        route = dict(row.get("entry_surface_route") or {})
        if _safe_bool(route.get("live_routable")) or _safe_bool(row.get("live_routable")):
            live_routable += 1
        else:
            context_only += 1
    return {"live_routable": live_routable, "context_only": context_only}


def _blocked_route_breakdown(snapshot: dict[str, Any]) -> dict[str, int]:
    existing = snapshot.get("blocked_setup_breakdown")
    if isinstance(existing, dict):
        return {
            "live_routable": int(existing.get("live_routable", 0) or 0),
            "context_only": int(existing.get("context_only", 0) or 0),
        }
    sections = dict(snapshot.get("sections") or {})
    return _blocked_route_breakdown_from_rows([dict(row) for row in list(sections.get(BLOCKED_SETUP) or [])])


def _result_count_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    counts = dict(snapshot.get("counts") or {})
    display_counts = dict(snapshot.get("display_counts") or counts)
    truncated_counts = dict(snapshot.get("truncated_counts") or {})
    live_order_candidates = int(counts.get(LIVE_ORDER_CANDIDATE, 0) or 0)
    context_review_setups = int(counts.get(CONTEXT_REVIEW_SETUP, 0) or 0)
    blocked_setups = int(counts.get(BLOCKED_SETUP, 0) or 0)
    research_only_setups = int(counts.get(RESEARCH_ONLY_SETUP, 0) or 0)
    blocked_breakdown = _blocked_route_breakdown(snapshot)
    blocked_live_order_candidates = int(blocked_breakdown.get("live_routable", 0) or 0)
    blocked_context_only_setups = int(blocked_breakdown.get("context_only", 0) or 0)
    return {
        "entry_counts": {
            LIVE_ORDER_CANDIDATE: live_order_candidates,
            CONTEXT_REVIEW_SETUP: context_review_setups,
            BLOCKED_SETUP: blocked_setups,
            RESEARCH_ONLY_SETUP: research_only_setups,
        },
        "source_counts": {
            LIVE_ORDER_CANDIDATE: live_order_candidates,
            CONTEXT_REVIEW_SETUP: context_review_setups,
            BLOCKED_SETUP: blocked_setups,
            RESEARCH_ONLY_SETUP: research_only_setups,
        },
        "display_counts": {
            LIVE_ORDER_CANDIDATE: int(display_counts.get(LIVE_ORDER_CANDIDATE, 0) or 0),
            CONTEXT_REVIEW_SETUP: int(display_counts.get(CONTEXT_REVIEW_SETUP, 0) or 0),
            BLOCKED_SETUP: int(display_counts.get(BLOCKED_SETUP, 0) or 0),
            RESEARCH_ONLY_SETUP: int(display_counts.get(RESEARCH_ONLY_SETUP, 0) or 0),
        },
        "truncated_entry_counts": {
            LIVE_ORDER_CANDIDATE: int(truncated_counts.get(LIVE_ORDER_CANDIDATE, 0) or 0),
            CONTEXT_REVIEW_SETUP: int(truncated_counts.get(CONTEXT_REVIEW_SETUP, 0) or 0),
            BLOCKED_SETUP: int(truncated_counts.get(BLOCKED_SETUP, 0) or 0),
            RESEARCH_ONLY_SETUP: int(truncated_counts.get(RESEARCH_ONLY_SETUP, 0) or 0),
        },
        "section_limit": int(snapshot.get("section_limit", 0) or 0),
        "blocked_setup_breakdown": {
            "live_routable": blocked_live_order_candidates,
            "context_only": blocked_context_only_setups,
        },
        "route_mismatch_summary": dict(snapshot.get("route_mismatch_summary") or {}),
        "operator_action_summary": dict(
            snapshot.get("operator_action_summary") or _entry_surface_operator_action(snapshot)
        ),
        "live_order_candidates": live_order_candidates,
        "blocked_live_order_candidates": blocked_live_order_candidates,
        "blocked_context_only_setups": blocked_context_only_setups,
        "context_review_setups": context_review_setups,
        "blocked_setups": blocked_setups,
        "research_only_setups": research_only_setups,
    }


def main() -> int:
    args = parse_args()
    now = datetime.now(UTC)
    quiet = bool(getattr(args, "quiet", False))
    state_file = _resolve_root_path(args.state_file).resolve()
    output_file_raw = str(getattr(args, "output_file", "") or "").strip()
    output_file = _resolve_root_path(output_file_raw).resolve() if output_file_raw else None
    lock_file_raw = str(getattr(args, "lock_file", "") or "").strip()
    lock_file = _resolve_root_path(lock_file_raw).resolve() if lock_file_raw else _default_lock_file(state_file)
    lock_fd = _try_acquire_lock(lock_file)
    if lock_fd is None:
        _emit_result(
            output_file,
            {
                "generated_at": now.isoformat(),
                "base_url": args.base_url,
                "universe": args.universe,
                "symbol": str(args.symbol or "").strip() or None,
                "channel": args.channel,
                "state_file": str(state_file),
                "lock_file": str(lock_file),
                "dry_run": bool(args.dry_run),
                "force_send": bool(args.force_send),
                "notified": False,
                "state_written": False,
                "dedupe_suppressed": True,
                "status": "WATCH",
                "overall_status": "WATCH",
                "status_detail": "entry_surface_previous_tick_still_running",
                "reason": "entry_surface_tick_already_running",
            },
            quiet=quiet,
        )
        return 0
    try:
        payload = _request_json(
            args.base_url,
            "GET",
            "/portfolio/budget",
        query={
            "universe": args.universe,
            "limit": args.limit,
            "write_report": "false",
            "fast": "true",
        },
    )
    except RuntimeError as exc:
        _emit_result(
            output_file,
            {
                "generated_at": now.isoformat(),
                "base_url": args.base_url,
                "universe": args.universe,
                "symbol": str(args.symbol or "").strip() or None,
                "channel": args.channel,
                "state_file": str(state_file),
                "lock_file": str(lock_file),
                "dry_run": bool(args.dry_run),
                "force_send": bool(args.force_send),
                "notified": False,
                "state_written": False,
                "dedupe_suppressed": False,
                "status": "FAIL",
                "overall_status": "FAIL",
                "status_detail": "entry_surface_source_request_failed",
                "reason": "source_request_failed",
                "error": str(exc),
            },
            quiet=quiet,
        )
        _release_lock(lock_fd)
        return 0
    snapshot = build_entry_snapshot(
        payload,
        symbol=str(args.symbol or "").strip(),
        max_per_status=max(0, int(args.max_per_status)),
    )
    alert_state = build_alert_state(snapshot)
    alert_state_signature = _alert_state_signature(alert_state)
    state_warning = ""
    try:
        previous_payload = _read_json(state_file)
    except RuntimeError as exc:
        previous_payload = None
        state_warning = str(exc)
    previous_state = _extract_alert_state(previous_payload)
    alert_state_history = _extract_alert_state_history(previous_payload)
    min_repeat_minutes = max(
        0,
        int(getattr(args, "min_repeat_minutes", _DEFAULT_REPEAT_SUPPRESSION_MINUTES) or 0),
    )

    result: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "base_url": args.base_url,
        "universe": args.universe,
        "symbol": str(args.symbol or "").strip() or None,
        "channel": args.channel,
        "state_file": str(state_file),
        "lock_file": str(lock_file),
        "dry_run": bool(args.dry_run),
        "force_send": bool(args.force_send),
        "min_repeat_minutes": min_repeat_minutes,
        "snapshot": snapshot,
        "alert_state": alert_state,
        "alert_state_signature": alert_state_signature,
        "notified": False,
        "state_written": False,
        "dedupe_suppressed": False,
        **_result_status_fields(snapshot),
        **_result_count_fields(snapshot),
    }
    message = render_message(snapshot)
    result["message"] = message
    if state_warning:
        result["state_warning"] = state_warning

    if not _has_alertable_rows(snapshot):
        result["reason"] = _no_alertable_reason(snapshot)
        result["legacy_reason"] = "no_alertable_rows"
        if not args.dry_run:
            _write_json(
                state_file,
                {
                    "updated_at": datetime.now(UTC).isoformat(),
                    "alert_state": alert_state,
                    "alert_state_signature": alert_state_signature,
                    "alert_state_history": alert_state_history,
                    "reason": result["reason"],
                    "legacy_reason": "no_alertable_rows",
                },
            )
            result["state_written"] = True
        _emit_result(output_file, result, quiet=quiet)
        _release_lock(lock_fd)
        return 0

    if previous_state == alert_state and not args.force_send:
        result["reason"] = "unchanged_surface_state"
        result["dedupe_suppressed"] = True
        _emit_result(output_file, result, quiet=quiet)
        _release_lock(lock_fd)
        return 0

    recently_seen, last_notified_at = _recent_history_match(
        alert_state_history,
        signature=alert_state_signature,
        now=now,
        min_repeat_minutes=min_repeat_minutes,
    )
    if recently_seen and not args.force_send:
        result["reason"] = "recent_surface_state_repeat"
        result["dedupe_suppressed"] = True
        result["last_notified_at"] = last_notified_at
        _emit_result(output_file, result, quiet=quiet)
        _release_lock(lock_fd)
        return 0

    if args.dry_run:
        result["reason"] = "dry_run"
        _emit_result(output_file, result, quiet=quiet)
        _release_lock(lock_fd)
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
    result["notified"] = _safe_bool(delivery.get("delivered"))
    result["delivery"] = delivery
    if _safe_bool(delivery.get("delivered")):
        updated_history = _updated_alert_state_history(
            alert_state_history,
            signature=alert_state_signature,
            now=now,
        )
        _write_json(
            state_file,
            {
                "updated_at": now.isoformat(),
                "alert_state": alert_state,
                "alert_state_signature": alert_state_signature,
                "alert_state_history": updated_history,
                "delivery": {
                    "channel": delivery.get("channel"),
                    "reason": delivery.get("reason"),
                    "target": delivery.get("target"),
                },
            },
        )
        result["state_written"] = True
    _emit_result(output_file, result, quiet=quiet)
    _release_lock(lock_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
