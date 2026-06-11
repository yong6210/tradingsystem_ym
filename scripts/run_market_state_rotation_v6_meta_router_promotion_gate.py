#!/usr/bin/env python3
"""Gate the adaptive meta-router candidate against readiness evidence.

This report is intentionally research/paper only. It links the formal shadow WFO
comparison to live-readiness output, but it never submits or enables live orders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]

DEFAULT_COMPARE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_meta_router_shadow_wfo_compare/"
    "market_state_rotation_v6_meta_router_shadow_wfo_compare.json"
)
DEFAULT_READINESS_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_live_readiness_meta_router_conditional_refill_formal/"
    "market_state_rotation_v6_live_readiness.json"
)
DEFAULT_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_meta_router_promotion_gate"
DEFAULT_CONDITIONAL_OVERFIT_HOLDOUT_AUDIT_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_conditional_overfit_holdout_audit/"
    "market_state_rotation_v6_conditional_overfit_holdout_audit.json"
)


ACCEPTED_LINEAGE_REVIEW_STATUSES = {
    "accepted",
    "operator_review_accepted",
    "operator_lineage_review_accepted",
}

ACCEPTED_CONDITIONAL_OVERFIT_REVIEW_STATUSES = {
    "accepted",
    "operator_review_accepted",
    "operator_overfit_review_accepted",
    "conditional_overfit_review_accepted",
}


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: str | Path | None) -> str | None:
    if path is None:
        return None
    resolved = _resolve(path)
    if resolved is None:
        return None
    try:
        return str(resolved.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(resolved)


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = _resolve(path)
    if resolved is None:
        raise ValueError("path is required")
    return dict(json.loads(resolved.read_text(encoding="utf-8")))


def _load_optional_json(path: str | Path | None) -> dict[str, Any] | None:
    resolved = _resolve(path)
    if resolved is None or not resolved.exists():
        return None
    return dict(json.loads(resolved.read_text(encoding="utf-8")))


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _fingerprint_payload(value: Any) -> str:
    normalized = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _operator_review_source_generated_at(operator_review: dict[str, Any]) -> datetime | None:
    acceptance = dict(operator_review.get("acceptance_contract") or {})
    return _parse_dt(
        operator_review.get("source_promotion_gate_generated_at")
        or operator_review.get("template_generated_at")
        or operator_review.get("promotion_gate_generated_at")
        or acceptance.get("reviewed_at_must_be_at_or_after_promotion_gate_generated_at")
    )


def _operator_review_source_report(operator_review: dict[str, Any]) -> str:
    acceptance = dict(operator_review.get("acceptance_contract") or {})
    return str(
        operator_review.get("source_promotion_gate_report")
        or acceptance.get("source_promotion_gate_report_must_match")
        or ""
    ).strip()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _pct(value: Any) -> float:
    return round(_float(value), 4)


def _nonzero_delta(value: Any, *, tolerance: float = 1e-6) -> bool:
    return abs(_float(value)) > tolerance


def _first_blocker(readiness: dict[str, Any]) -> str | None:
    blockers = list(readiness.get("blockers") or [])
    if blockers:
        return str(blockers[0])
    stage_blockers = dict(readiness.get("stage_blockers") or {})
    for stage in ("paper", "tiny_canary", "full_live"):
        nested = list(stage_blockers.get(stage) or [])
        if nested:
            return str(nested[0])
    return None


def _normalize_report_path(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _readiness_candidate_alignment(
    *,
    candidate: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    candidate_report = _normalize_report_path(candidate.get("report_path"))
    readiness_walk_report = _normalize_report_path(
        readiness.get("input_walk_report") or readiness.get("input_walk_forward_report")
    )
    if not candidate_report or not readiness_walk_report:
        return {
            "passed": False,
            "candidate_report_path": candidate_report or None,
            "readiness_walk_report": readiness_walk_report or None,
            "blockers": ["readiness_candidate_report_path_missing"],
        }
    passed = candidate_report == readiness_walk_report
    return {
        "passed": passed,
        "candidate_report_path": candidate_report,
        "readiness_walk_report": readiness_walk_report,
        "blockers": [] if passed else ["readiness_candidate_report_mismatch"],
    }


def _candidate_execution_change_audit(
    *,
    candidate_metrics: dict[str, Any],
    compare_candidate: dict[str, Any],
) -> dict[str, Any]:
    upstream = dict(compare_candidate.get("execution_change_audit") or {})
    if upstream:
        return {
            "status": upstream.get("status"),
            "execution_delta_detected": bool(upstream.get("execution_delta_detected")),
            "metric_delta_detected": bool(upstream.get("metric_delta_detected")),
            "beneficial_metric_delta_detected": bool(upstream.get("beneficial_metric_delta_detected")),
            "performance_upgrade_ready": bool(upstream.get("performance_upgrade_ready")),
            "risk_compression_detected": bool(upstream.get("risk_compression_detected")),
            "risk_compression_ready": bool(upstream.get("risk_compression_ready")),
            "risk_adjusted_compression_ready": bool(
                upstream.get("risk_adjusted_compression_ready")
            ),
            "return_delta_vs_baseline_pct": _pct(upstream.get("return_delta_vs_baseline_pct")),
            "return_giveback_fraction_vs_baseline": _pct(
                upstream.get("return_giveback_fraction_vs_baseline")
            ),
            "drawdown_delta_vs_baseline_pct": _pct(upstream.get("drawdown_delta_vs_baseline_pct")),
            "drawdown_reduction_fraction_vs_baseline": _pct(
                upstream.get("drawdown_reduction_fraction_vs_baseline")
            ),
            "cost_delta_vs_baseline_pct": _pct(upstream.get("cost_delta_vs_baseline_pct")),
            "trade_event_delta_vs_baseline": int(upstream.get("trade_event_delta_vs_baseline") or 0),
            "candidate_trade_like_events": int(upstream.get("candidate_trade_like_events") or 0),
            "baseline_trade_like_events": int(upstream.get("baseline_trade_like_events") or 0),
            "active_router_modes": list(upstream.get("active_router_modes") or []),
            "blockers": list(upstream.get("blockers") or []),
            "notes": list(upstream.get("notes") or []),
        }

    return_delta = _float(candidate_metrics.get("return_delta_vs_baseline_pct"))
    drawdown_delta = _float(candidate_metrics.get("drawdown_delta_vs_baseline_pct"))
    cost_delta = _float(candidate_metrics.get("cost_delta_vs_baseline_pct"))
    trade_event_delta = int(candidate_metrics.get("trade_event_delta_vs_baseline") or 0)
    metric_delta_detected = any(
        [
            _nonzero_delta(return_delta),
            _nonzero_delta(drawdown_delta),
            _nonzero_delta(cost_delta),
        ]
    )
    execution_delta_detected = metric_delta_detected or trade_event_delta != 0
    beneficial_metric_delta_detected = (
        (return_delta > 0.0 or drawdown_delta < 0.0 or cost_delta < 0.0)
        and return_delta >= 0.0
        and drawdown_delta <= 0.0
        and cost_delta <= 0.0
    )
    risk_compression_detected = drawdown_delta < 0.0 and cost_delta <= 0.0
    risk_compression_ready = risk_compression_detected and return_delta >= 0.0
    mode_summary = dict(candidate_metrics.get("router_mode_summary") or {})
    active_modes = list(mode_summary.get("active_modes") or [])
    blockers: list[str] = []
    notes: list[str] = []
    if not execution_delta_detected:
        blockers.append("candidate_does_not_change_return_drawdown_cost_or_trade_events")
        if active_modes:
            notes.append("router_modes_are_descriptive_only_for_this_candidate")
    if execution_delta_detected and not beneficial_metric_delta_detected:
        notes.append("execution_changed_without_non_worse_return_drawdown_and_cost_profile")
    status = (
        "performance_metric_delta_detected"
        if beneficial_metric_delta_detected
        else (
            "execution_delta_without_metric_improvement"
            if execution_delta_detected
            else "decomposition_only_no_execution_delta"
        )
    )
    return {
        "status": status,
        "execution_delta_detected": execution_delta_detected,
        "metric_delta_detected": metric_delta_detected,
        "beneficial_metric_delta_detected": beneficial_metric_delta_detected,
        "performance_upgrade_ready": beneficial_metric_delta_detected,
        "risk_compression_detected": risk_compression_detected,
        "risk_compression_ready": risk_compression_ready,
        "risk_adjusted_compression_ready": False,
        "return_delta_vs_baseline_pct": _pct(return_delta),
        "return_giveback_fraction_vs_baseline": None,
        "drawdown_delta_vs_baseline_pct": _pct(drawdown_delta),
        "drawdown_reduction_fraction_vs_baseline": None,
        "cost_delta_vs_baseline_pct": _pct(cost_delta),
        "trade_event_delta_vs_baseline": trade_event_delta,
        "candidate_trade_like_events": int(candidate_metrics.get("trade_like_events") or 0),
        "baseline_trade_like_events": None,
        "active_router_modes": active_modes,
        "blockers": blockers,
        "notes": notes,
    }


def _compare_candidate_summary(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    candidate = dict(candidate or {})
    metrics = dict(candidate.get("candidate") or {})
    audit = dict(candidate.get("execution_change_audit") or {})
    overfit_audit = dict(candidate.get("overfit_audit") or {})
    return {
        "recipe_id": candidate.get("recipe_id"),
        "decision": candidate.get("decision"),
        "report_path": candidate.get("report_path"),
        "fold_count": int(metrics.get("fold_count") or 0),
        "compounded_return_pct": _pct(metrics.get("compounded_return_pct")),
        "max_drawdown_pct": _pct(metrics.get("max_drawdown_pct")),
        "avg_cost_drag_pct": _pct(metrics.get("avg_cost_drag_pct")),
        "return_delta_vs_baseline_pct": _pct(audit.get("return_delta_vs_baseline_pct")),
        "drawdown_delta_vs_baseline_pct": _pct(audit.get("drawdown_delta_vs_baseline_pct")),
        "cost_delta_vs_baseline_pct": _pct(audit.get("cost_delta_vs_baseline_pct")),
        "trade_event_delta_vs_baseline": int(audit.get("trade_event_delta_vs_baseline") or 0),
        "execution_delta_status": audit.get("status"),
        "performance_upgrade_ready": bool(audit.get("performance_upgrade_ready")),
        "risk_compression_detected": bool(audit.get("risk_compression_detected")),
        "risk_compression_ready": bool(audit.get("risk_compression_ready")),
        "risk_adjusted_compression_ready": bool(audit.get("risk_adjusted_compression_ready")),
        "return_giveback_fraction_vs_baseline": _pct(
            audit.get("return_giveback_fraction_vs_baseline")
        ),
        "drawdown_reduction_fraction_vs_baseline": _pct(
            audit.get("drawdown_reduction_fraction_vs_baseline")
        ),
        "blockers": list(audit.get("blockers") or []),
        "overfit_audit_status": overfit_audit.get("status"),
        "overfit_audit_blockers": list(overfit_audit.get("blockers") or []),
    }


def _conditional_overfit_holdout_audit_summary(
    *,
    candidate: dict[str, Any],
    audit_report: dict[str, Any] | None,
    input_report: str | None,
) -> dict[str, Any]:
    if not audit_report:
        return {
            "status": "unavailable",
            "reason": "conditional_overfit_holdout_audit_missing",
            "input_report": input_report,
            "proxy_passed": False,
            "real_shadow_still_required": True,
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }
    candidate_report = _normalize_report_path(candidate.get("report_path"))
    audit_candidate_report = _normalize_report_path(audit_report.get("candidate_report"))
    candidate_report_matched = bool(candidate_report) and candidate_report == audit_candidate_report
    proxy_passed = (
        str(audit_report.get("status") or "") == "historical_proxy_pass_real_shadow_required"
        and candidate_report_matched
        and not list(audit_report.get("blockers") or [])
    )
    blockers = list(audit_report.get("blockers") or [])
    if not candidate_report_matched:
        blockers.append("conditional_overfit_holdout_audit_candidate_report_mismatch")
    return {
        "status": audit_report.get("status"),
        "input_report": input_report,
        "candidate_report_matched": candidate_report_matched,
        "candidate_report": candidate_report,
        "audit_candidate_report": audit_candidate_report,
        "proxy_passed": proxy_passed,
        "real_shadow_still_required": True,
        "aggregate_delta": dict(audit_report.get("aggregate_delta") or {}),
        "fold_delta_summary": dict(audit_report.get("fold_delta_summary") or {}),
        "tail_holdout_proxy": dict(audit_report.get("tail_holdout_proxy") or {}),
        "conditional_token_proxy": dict(audit_report.get("conditional_token_proxy") or {}),
        "blockers": blockers,
        "warnings": list(audit_report.get("warnings") or []),
        "limitations": list(audit_report.get("limitations") or []),
        "next_action": audit_report.get("next_action"),
        "order_submission_allowed": False,
        "no_live_order_sent": audit_report.get("no_live_order_sent") is True,
    }


def _conditional_overfit_review_packet(
    *,
    candidate: dict[str, Any],
    overfit_audit: dict[str, Any],
    conditional_holdout: dict[str, Any],
) -> dict[str, Any]:
    return {
        "summary": "conditional_winner_refill_overlay_historical_proxy_requires_operator_overfit_review",
        "candidate_recipe_id": candidate.get("recipe_id"),
        "candidate_report": candidate.get("report_path"),
        "overfit_audit_status": overfit_audit.get("status"),
        "overfit_blockers": list(overfit_audit.get("blockers") or []),
        "conditional_model_token": overfit_audit.get("conditional_model_token"),
        "proxy_audit_report": conditional_holdout.get("input_report"),
        "proxy_status": conditional_holdout.get("status"),
        "proxy_passed": conditional_holdout.get("proxy_passed") is True,
        "aggregate_delta": dict(conditional_holdout.get("aggregate_delta") or {}),
        "tail_holdout_proxy": dict(conditional_holdout.get("tail_holdout_proxy") or {}),
        "conditional_token_proxy": dict(conditional_holdout.get("conditional_token_proxy") or {}),
        "fold_delta_summary": dict(conditional_holdout.get("fold_delta_summary") or {}),
        "warnings": list(conditional_holdout.get("warnings") or []),
        "limitations": list(conditional_holdout.get("limitations") or []),
        "real_shadow_still_required_before_tiny_canary_or_live": True,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _conditional_overfit_review_template(
    *,
    candidate: dict[str, Any],
    overfit_audit: dict[str, Any],
    conditional_holdout: dict[str, Any],
) -> dict[str, Any]:
    packet = _conditional_overfit_review_packet(
        candidate=candidate,
        overfit_audit=overfit_audit,
        conditional_holdout=conditional_holdout,
    )
    packet_fingerprint = _fingerprint_payload(packet)
    return {
        "status": "pending_conditional_overfit_operator_review",
        "candidate_recipe_id": candidate.get("recipe_id"),
        "candidate_report": candidate.get("report_path"),
        "overfit_blockers": list(overfit_audit.get("blockers") or []),
        "proxy_audit_report": conditional_holdout.get("input_report"),
        "proxy_status": conditional_holdout.get("status"),
        "proxy_passed": conditional_holdout.get("proxy_passed") is True,
        "review_packet_summary": packet.get("summary"),
        "review_packet_fingerprint": packet_fingerprint,
        "required_decision_values": sorted(ACCEPTED_CONDITIONAL_OVERFIT_REVIEW_STATUSES),
        "required_no_live_order_sent": True,
        "required_operator_rationale": True,
        "required_operator_reviewed_at": True,
        "paper_only_scope": True,
        "real_shadow_still_required_before_tiny_canary_or_live": True,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _apply_conditional_overfit_operator_review(
    *,
    candidate: dict[str, Any],
    overfit_audit: dict[str, Any],
    conditional_holdout: dict[str, Any],
    operator_review_report: dict[str, Any] | None,
    promotion_gate_generated_at: datetime,
    expected_source_promotion_gate_report: str | None = None,
) -> dict[str, Any]:
    overfit_blockers = list(overfit_audit.get("blockers") or [])
    required = bool(overfit_blockers)
    proxy_passed = conditional_holdout.get("proxy_passed") is True
    template = (
        _conditional_overfit_review_template(
            candidate=candidate,
            overfit_audit=overfit_audit,
            conditional_holdout=conditional_holdout,
        )
        if required and proxy_passed
        else {}
    )
    base = {
        "required": required,
        "status": "not_required" if not required else "pending_conditional_overfit_operator_review",
        "proxy_passed": proxy_passed,
        "accepted_for_paper_only": False,
        "paper_only_scope": True,
        "real_shadow_still_required_before_tiny_canary_or_live": bool(required),
        "operator_review_template": template,
        "blockers": [],
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    if not required:
        return base
    if not proxy_passed:
        return {
            **base,
            "status": "pending_conditional_overfit_holdout_proxy",
            "blockers": ["conditional_overfit_holdout_proxy_not_passed"],
            "operator_review": {
                "status": "not_applicable_until_proxy_passes",
                "matched": False,
                "blockers": ["conditional_overfit_holdout_proxy_not_passed"],
                "no_live_order_sent": True,
            },
        }

    operator_review = dict(operator_review_report or {})
    if not operator_review:
        return {
            **base,
            "operator_review": {
                "status": "missing",
                "matched": False,
                "blockers": ["conditional_overfit_operator_review_report_missing"],
                "no_live_order_sent": True,
            },
            "blockers": ["conditional_overfit_operator_review_report_missing"],
        }

    status = _review_status(operator_review)
    expected_recipe = str(candidate.get("recipe_id") or "")
    review_recipe = str(operator_review.get("candidate_recipe_id") or operator_review.get("recipe_id") or "")
    expected_candidate_report = str(candidate.get("report_path") or "").strip()
    review_candidate_report = str(operator_review.get("candidate_report") or "").strip()
    expected_proxy_report = str(conditional_holdout.get("input_report") or "").strip()
    review_proxy_report = str(
        operator_review.get("proxy_audit_report")
        or operator_review.get("conditional_overfit_holdout_audit_report")
        or ""
    ).strip()
    expected_blockers = [str(item) for item in overfit_blockers]
    review_blockers = [str(item) for item in list(operator_review.get("overfit_blockers") or [])]
    expected_summary = str(template.get("review_packet_summary") or "")
    review_summary = str(operator_review.get("review_packet_summary") or operator_review.get("summary") or "")
    expected_fingerprint = str(template.get("review_packet_fingerprint") or "")
    review_fingerprint = str(
        operator_review.get("review_packet_fingerprint")
        or operator_review.get("overfit_review_packet_fingerprint")
        or operator_review.get("fingerprint")
        or ""
    )
    reviewer = str(operator_review.get("reviewer") or "").strip()
    rationale = str(operator_review.get("rationale") or "").strip()
    reviewed_at = _parse_dt(
        operator_review.get("reviewed_at")
        or operator_review.get("accepted_at")
        or operator_review.get("operator_reviewed_at")
    )
    source_generated_at = _operator_review_source_generated_at(operator_review)
    source_report = _operator_review_source_report(operator_review)
    validation_generated_at = promotion_gate_generated_at.astimezone(UTC)
    expected_source_report = str(expected_source_promotion_gate_report or "").strip()

    blockers: list[str] = []
    if operator_review.get("no_live_order_sent") is not True:
        blockers.append("conditional_overfit_operator_review_no_live_order_sent_not_true")
    if expected_recipe and review_recipe != expected_recipe:
        blockers.append("conditional_overfit_operator_review_candidate_mismatch")
    if expected_candidate_report and review_candidate_report != expected_candidate_report:
        blockers.append("conditional_overfit_operator_review_candidate_report_mismatch")
    if expected_proxy_report and review_proxy_report != expected_proxy_report:
        blockers.append("conditional_overfit_operator_review_proxy_report_mismatch")
    if expected_blockers and review_blockers != expected_blockers:
        blockers.append("conditional_overfit_operator_review_blockers_mismatch")
    if expected_summary and review_summary != expected_summary:
        blockers.append("conditional_overfit_operator_review_summary_mismatch")
    if expected_fingerprint and review_fingerprint != expected_fingerprint:
        blockers.append("conditional_overfit_operator_review_fingerprint_mismatch")
    if status not in ACCEPTED_CONDITIONAL_OVERFIT_REVIEW_STATUSES:
        blockers.append("conditional_overfit_operator_review_not_accepted")
    if operator_review.get("paper_only_scope") is not True:
        blockers.append("conditional_overfit_operator_review_paper_only_scope_not_true")
    if operator_review.get("real_shadow_still_required_before_tiny_canary_or_live") is not True:
        blockers.append("conditional_overfit_operator_review_real_shadow_requirement_not_acknowledged")
    if status in ACCEPTED_CONDITIONAL_OVERFIT_REVIEW_STATUSES:
        if expected_source_report:
            if not source_report:
                blockers.append("conditional_overfit_operator_review_source_promotion_gate_report_missing")
            elif source_report != expected_source_report:
                blockers.append("conditional_overfit_operator_review_source_promotion_gate_report_mismatch")
        if source_generated_at is None:
            blockers.append("conditional_overfit_operator_review_source_promotion_gate_generated_at_missing_or_invalid")
        elif source_generated_at > validation_generated_at + timedelta(minutes=5):
            blockers.append("conditional_overfit_operator_review_source_promotion_gate_generated_at_in_future")
        if reviewed_at is None:
            blockers.append("conditional_overfit_operator_review_reviewed_at_missing_or_invalid")
        elif source_generated_at is not None and reviewed_at < source_generated_at:
            blockers.append("conditional_overfit_operator_review_reviewed_before_promotion_gate")
        elif reviewed_at > validation_generated_at + timedelta(minutes=5):
            blockers.append("conditional_overfit_operator_review_reviewed_at_in_future")
        if not reviewer:
            blockers.append("conditional_overfit_operator_review_reviewer_missing")
        if not rationale:
            blockers.append("conditional_overfit_operator_review_rationale_missing")

    accepted = not blockers
    review_state = {
        "status": status or "missing_status",
        "matched": accepted,
        "candidate_recipe_id": review_recipe or None,
        "candidate_report": review_candidate_report or None,
        "proxy_audit_report": review_proxy_report or None,
        "overfit_blockers": review_blockers,
        "review_packet_summary": review_summary or None,
        "review_packet_fingerprint": review_fingerprint or None,
        "source_promotion_gate_report": source_report or None,
        "expected_source_promotion_gate_report": expected_source_report or None,
        "source_promotion_gate_generated_at": (
            source_generated_at.isoformat() if source_generated_at is not None else None
        ),
        "reviewed_at": reviewed_at.isoformat() if reviewed_at is not None else None,
        "validation_generated_at": validation_generated_at.isoformat(),
        "reviewer": reviewer or None,
        "rationale": rationale or None,
        "blockers": sorted(set(blockers)),
        "no_live_order_sent": operator_review.get("no_live_order_sent") is True,
    }
    return {
        **base,
        "status": (
            "conditional_overfit_operator_review_accepted_for_paper_only"
            if accepted
            else "pending_conditional_overfit_operator_review"
        ),
        "accepted_for_paper_only": accepted,
        "operator_review": review_state,
        "blockers": sorted(set(blockers)),
    }


def _review_status(value: dict[str, Any]) -> str:
    return str(value.get("status") or value.get("decision") or "").strip()


def _review_folds(value: dict[str, Any]) -> list[int]:
    raw = (
        value.get("reviewed_folds")
        or value.get("unresolved_material_folds")
        or value.get("folds")
        or []
    )
    folds: list[int] = []
    for item in list(raw or []):
        try:
            folds.append(int(item))
        except (TypeError, ValueError):
            continue
    return folds


def _lineage_review_template(
    *,
    defensive_lineage_review: dict[str, Any],
    defensive_candidate: dict[str, Any],
) -> dict[str, Any]:
    packet = dict(defensive_lineage_review.get("review_packet") or {})
    packet_fingerprint = _fingerprint_payload(packet)
    return {
        "status": "pending_operator_lineage_review",
        "candidate_recipe_id": defensive_candidate.get("recipe_id"),
        "reviewed_folds": list(defensive_lineage_review.get("unresolved_material_folds") or []),
        "review_packet_summary": packet.get("summary"),
        "review_packet_fingerprint": packet_fingerprint,
        "required_decision_values": sorted(ACCEPTED_LINEAGE_REVIEW_STATUSES),
        "required_no_live_order_sent": True,
        "required_operator_rationale": True,
        "required_operator_reviewed_at": True,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _apply_operator_lineage_review(
    *,
    defensive_lineage_review: dict[str, Any],
    defensive_candidate: dict[str, Any],
    operator_lineage_review: dict[str, Any] | None,
    promotion_gate_generated_at: datetime,
    expected_source_promotion_gate_report: str | None = None,
) -> dict[str, Any]:
    review = dict(defensive_lineage_review or {})
    review["operator_review_template"] = _lineage_review_template(
        defensive_lineage_review=review,
        defensive_candidate=defensive_candidate,
    )
    operator_review = dict(operator_lineage_review or {})
    if not operator_review:
        review["operator_review"] = {
            "status": "missing",
            "matched": False,
            "blockers": ["operator_lineage_review_report_missing"],
            "no_live_order_sent": True,
        }
        return review

    packet = dict(review.get("review_packet") or {})
    expected_recipe = str(defensive_candidate.get("recipe_id") or "")
    review_recipe = str(
        operator_review.get("candidate_recipe_id")
        or operator_review.get("defensive_candidate_recipe_id")
        or operator_review.get("recipe_id")
        or ""
    )
    expected_folds = [int(item) for item in list(review.get("unresolved_material_folds") or [])]
    review_folds = _review_folds(operator_review)
    expected_summary = str(packet.get("summary") or "")
    review_summary = str(
        operator_review.get("review_packet_summary")
        or operator_review.get("lineage_review_summary")
        or operator_review.get("summary")
        or ""
    )
    expected_fingerprint = _fingerprint_payload(packet)
    review_fingerprint = str(
        operator_review.get("review_packet_fingerprint")
        or operator_review.get("lineage_review_fingerprint")
        or operator_review.get("fingerprint")
        or ""
    )
    status = _review_status(operator_review)
    reviewer = str(operator_review.get("reviewer") or "").strip()
    rationale = str(operator_review.get("rationale") or "").strip()
    reviewed_at = _parse_dt(
        operator_review.get("reviewed_at")
        or operator_review.get("accepted_at")
        or operator_review.get("operator_reviewed_at")
    )
    source_generated_at = _operator_review_source_generated_at(operator_review)
    source_report = _operator_review_source_report(operator_review)
    validation_generated_at = promotion_gate_generated_at.astimezone(UTC)
    expected_source_report = str(expected_source_promotion_gate_report or "").strip()
    blockers: list[str] = []
    if operator_review.get("no_live_order_sent") is not True:
        blockers.append("operator_lineage_review_no_live_order_sent_not_true")
    if expected_recipe and review_recipe != expected_recipe:
        blockers.append("operator_lineage_review_candidate_mismatch")
    if expected_folds and review_folds != expected_folds:
        blockers.append("operator_lineage_review_folds_mismatch")
    if expected_summary and review_summary != expected_summary:
        blockers.append("operator_lineage_review_summary_mismatch")
    if expected_fingerprint and review_fingerprint != expected_fingerprint:
        blockers.append("operator_lineage_review_fingerprint_mismatch")
    if status not in ACCEPTED_LINEAGE_REVIEW_STATUSES:
        blockers.append("operator_lineage_review_not_accepted")
    if status in ACCEPTED_LINEAGE_REVIEW_STATUSES:
        if expected_source_report:
            if not source_report:
                blockers.append("operator_lineage_review_source_promotion_gate_report_missing")
            elif source_report != expected_source_report:
                blockers.append("operator_lineage_review_source_promotion_gate_report_mismatch")
        if source_generated_at is None:
            blockers.append("operator_lineage_review_source_promotion_gate_generated_at_missing_or_invalid")
        elif source_generated_at > validation_generated_at + timedelta(minutes=5):
            blockers.append("operator_lineage_review_source_promotion_gate_generated_at_in_future")
        if reviewed_at is None:
            blockers.append("operator_lineage_review_reviewed_at_missing_or_invalid")
        elif source_generated_at is not None and reviewed_at < source_generated_at:
            blockers.append("operator_lineage_review_reviewed_before_promotion_gate")
        elif reviewed_at > validation_generated_at + timedelta(minutes=5):
            blockers.append("operator_lineage_review_reviewed_at_in_future")
        if not reviewer:
            blockers.append("operator_lineage_review_reviewer_missing")
        if not rationale:
            blockers.append("operator_lineage_review_rationale_missing")

    accepted = not blockers
    if accepted:
        review["status"] = "operator_lineage_review_accepted"
        review["blockers"] = []
    elif status in {"rejected", "operator_lineage_review_rejected", "operator_review_rejected"}:
        review["status"] = "operator_lineage_review_rejected"
        blockers.append("defensive_lineage_review_rejected")
    else:
        review["status"] = "pending_operator_lineage_review"

    review["operator_review"] = {
        "status": status or "missing_status",
        "matched": accepted,
        "candidate_recipe_id": review_recipe or None,
        "reviewed_folds": review_folds,
        "review_packet_summary": review_summary or None,
        "review_packet_fingerprint": review_fingerprint or None,
        "reviewed_at": reviewed_at.isoformat() if reviewed_at is not None else None,
        "source_promotion_gate_report": source_report or None,
        "expected_source_promotion_gate_report": expected_source_report or None,
        "source_promotion_gate_generated_at": (
            source_generated_at.isoformat() if source_generated_at is not None else None
        ),
        "validation_generated_at": validation_generated_at.isoformat(),
        "blockers": sorted(set(blockers)),
        "source": operator_review.get("source_report"),
        "reviewer": reviewer or None,
        "rationale": rationale or None,
        "no_live_order_sent": operator_review.get("no_live_order_sent") is True,
    }
    if not accepted:
        review["blockers"] = sorted(
            set(list(review.get("blockers") or []) + list(review["operator_review"]["blockers"]))
        )
    review["no_live_order_sent"] = True
    return review


def _operator_lineage_review_template_report(
    *,
    report: dict[str, Any],
    source_promotion_gate_report: str | Path | None = None,
) -> dict[str, Any] | None:
    switch_policy = dict(report.get("candidate_switch_policy") or {})
    defensive_lineage_review = dict(switch_policy.get("defensive_lineage_review") or {})
    if defensive_lineage_review.get("required") is not True:
        return None
    template = dict(defensive_lineage_review.get("operator_review_template") or {})
    if not template:
        return None
    review_packet = dict(defensive_lineage_review.get("review_packet") or {})
    source_report = _display_path(source_promotion_gate_report)
    expected_source_arg = shlex.quote(source_report or "<source_promotion_gate_report>")
    return {
        "generated_at": report.get("generated_at"),
        "status": "pending_operator_lineage_review",
        "purpose": "operator_review_template_for_defensive_candidate_route",
        "source_promotion_gate_report": source_report,
        "source_promotion_gate_generated_at": report.get("generated_at"),
        "candidate_recipe_id": template.get("candidate_recipe_id"),
        "reviewed_folds": list(template.get("reviewed_folds") or []),
        "review_packet_summary": template.get("review_packet_summary"),
        "review_packet_fingerprint": template.get("review_packet_fingerprint"),
        "review_packet": review_packet,
        "required_decision_values": list(template.get("required_decision_values") or []),
        "operator_fields_to_fill": {
            "status": "operator_lineage_review_accepted_or_rejected",
            "source_promotion_gate_report": source_report,
            "reviewer": "operator_name_or_initials",
            "reviewed_at": "iso8601_timestamp_after_this_template_was_generated",
            "rationale": "why_the_defensive_size_overlay_delta_is_accepted_or_rejected",
            "no_live_order_sent": True,
        },
        "operator_review_json_skeleton": {
            "status": "operator_lineage_review_accepted_or_rejected",
            "candidate_recipe_id": template.get("candidate_recipe_id"),
            "reviewed_folds": list(template.get("reviewed_folds") or []),
            "review_packet_summary": template.get("review_packet_summary"),
            "review_packet_fingerprint": template.get("review_packet_fingerprint"),
            "source_promotion_gate_report": source_report,
            "source_promotion_gate_generated_at": report.get("generated_at"),
            "reviewer": "operator_name_or_initials",
            "reviewed_at": "iso8601_timestamp_after_this_template_was_generated",
            "rationale": "why_the_defensive_size_overlay_delta_is_accepted_or_rejected",
            "acceptance_contract": {
                "source_promotion_gate_report_must_match": source_report,
                "candidate_recipe_id_must_match": template.get("candidate_recipe_id"),
                "reviewed_folds_must_match": list(template.get("reviewed_folds") or []),
                "review_packet_summary_must_match": template.get("review_packet_summary"),
                "review_packet_fingerprint_must_match": template.get("review_packet_fingerprint"),
                "reviewed_at_must_be_at_or_after_promotion_gate_generated_at": report.get("generated_at"),
                "reviewer_must_be_non_empty": True,
                "rationale_must_be_non_empty": True,
                "no_live_order_sent_must_be_true": True,
                "accepted_status_values": list(template.get("required_decision_values") or []),
            },
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        },
        "acceptance_contract": {
            "source_promotion_gate_report_must_match": source_report,
            "candidate_recipe_id_must_match": template.get("candidate_recipe_id"),
            "reviewed_folds_must_match": list(template.get("reviewed_folds") or []),
            "review_packet_summary_must_match": template.get("review_packet_summary"),
            "review_packet_fingerprint_must_match": template.get("review_packet_fingerprint"),
            "reviewed_at_must_be_at_or_after_promotion_gate_generated_at": report.get("generated_at"),
            "reviewer_must_be_non_empty": True,
            "rationale_must_be_non_empty": True,
            "no_live_order_sent_must_be_true": True,
            "accepted_status_values": list(template.get("required_decision_values") or []),
        },
        "validation_command_template": (
            ".venv/bin/python scripts/run_market_state_rotation_v6_meta_router_promotion_gate.py "
            "--operator-lineage-review-report <operator_lineage_review_report.json> "
            f"--expected-operator-lineage-source-report {expected_source_arg}"
        ),
        "validation_contract": {
            "purpose": "validate_operator_lineage_review_before_writing_or_promoting_any_route",
            "expected_operator_lineage_source_report": source_report,
            "expected_operator_review_status_path": (
                "candidate_switch_policy.defensive_lineage_review.operator_review.status"
            ),
            "expected_no_live_order_sent": True,
            "write_report_required_for_validation": False,
            "order_submission_allowed": False,
        },
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _conditional_overfit_operator_review_template_report(
    *,
    report: dict[str, Any],
    source_promotion_gate_report: str | Path | None = None,
) -> dict[str, Any] | None:
    review = dict(report.get("conditional_overfit_operator_review") or {})
    if review.get("required") is not True:
        return None
    if review.get("proxy_passed") is not True:
        return None
    template = dict(review.get("operator_review_template") or {})
    if not template:
        return None
    candidate = dict(report.get("candidate") or {})
    conditional_holdout = dict(report.get("conditional_overfit_holdout_audit") or {})
    overfit_audit = dict(candidate.get("overfit_audit") or report.get("overfit_audit") or {})
    review_packet = _conditional_overfit_review_packet(
        candidate=candidate,
        overfit_audit=overfit_audit,
        conditional_holdout=conditional_holdout,
    )
    source_report = _display_path(source_promotion_gate_report)
    expected_source_arg = shlex.quote(source_report or "<source_promotion_gate_report>")
    return {
        "generated_at": report.get("generated_at"),
        "status": "pending_conditional_overfit_operator_review",
        "purpose": "operator_review_template_for_conditional_overfit_holdout_proxy",
        "source_promotion_gate_report": source_report,
        "source_promotion_gate_generated_at": report.get("generated_at"),
        "candidate_recipe_id": template.get("candidate_recipe_id"),
        "candidate_report": template.get("candidate_report"),
        "overfit_blockers": list(template.get("overfit_blockers") or []),
        "proxy_audit_report": template.get("proxy_audit_report"),
        "proxy_status": template.get("proxy_status"),
        "proxy_passed": template.get("proxy_passed") is True,
        "review_packet_summary": template.get("review_packet_summary"),
        "review_packet_fingerprint": template.get("review_packet_fingerprint"),
        "review_packet": review_packet,
        "required_decision_values": list(template.get("required_decision_values") or []),
        "paper_only_scope": True,
        "real_shadow_still_required_before_tiny_canary_or_live": True,
        "operator_fields_to_fill": {
            "status": "conditional_overfit_review_accepted_or_rejected",
            "source_promotion_gate_report": source_report,
            "reviewer": "operator_name_or_initials",
            "reviewed_at": "iso8601_timestamp_after_this_template_was_generated",
            "rationale": (
                "why_the_conditional_overlay_proxy_evidence_is_accepted_or_rejected_for_paper_only"
            ),
            "paper_only_scope": True,
            "real_shadow_still_required_before_tiny_canary_or_live": True,
            "no_live_order_sent": True,
        },
        "operator_review_json_skeleton": {
            "status": "conditional_overfit_review_accepted_or_rejected",
            "candidate_recipe_id": template.get("candidate_recipe_id"),
            "candidate_report": template.get("candidate_report"),
            "overfit_blockers": list(template.get("overfit_blockers") or []),
            "proxy_audit_report": template.get("proxy_audit_report"),
            "review_packet_summary": template.get("review_packet_summary"),
            "review_packet_fingerprint": template.get("review_packet_fingerprint"),
            "source_promotion_gate_report": source_report,
            "source_promotion_gate_generated_at": report.get("generated_at"),
            "reviewer": "operator_name_or_initials",
            "reviewed_at": "iso8601_timestamp_after_this_template_was_generated",
            "rationale": (
                "why_the_conditional_overlay_proxy_evidence_is_accepted_or_rejected_for_paper_only"
            ),
            "paper_only_scope": True,
            "real_shadow_still_required_before_tiny_canary_or_live": True,
            "acceptance_contract": {
                "source_promotion_gate_report_must_match": source_report,
                "candidate_recipe_id_must_match": template.get("candidate_recipe_id"),
                "candidate_report_must_match": template.get("candidate_report"),
                "overfit_blockers_must_match": list(template.get("overfit_blockers") or []),
                "proxy_audit_report_must_match": template.get("proxy_audit_report"),
                "review_packet_summary_must_match": template.get("review_packet_summary"),
                "review_packet_fingerprint_must_match": template.get("review_packet_fingerprint"),
                "reviewed_at_must_be_at_or_after_promotion_gate_generated_at": report.get("generated_at"),
                "reviewer_must_be_non_empty": True,
                "rationale_must_be_non_empty": True,
                "paper_only_scope_must_be_true": True,
                "real_shadow_still_required_before_tiny_canary_or_live_must_be_true": True,
                "no_live_order_sent_must_be_true": True,
                "accepted_status_values": list(template.get("required_decision_values") or []),
            },
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        },
        "acceptance_contract": {
            "source_promotion_gate_report_must_match": source_report,
            "candidate_recipe_id_must_match": template.get("candidate_recipe_id"),
            "candidate_report_must_match": template.get("candidate_report"),
            "overfit_blockers_must_match": list(template.get("overfit_blockers") or []),
            "proxy_audit_report_must_match": template.get("proxy_audit_report"),
            "review_packet_summary_must_match": template.get("review_packet_summary"),
            "review_packet_fingerprint_must_match": template.get("review_packet_fingerprint"),
            "reviewed_at_must_be_at_or_after_promotion_gate_generated_at": report.get("generated_at"),
            "reviewer_must_be_non_empty": True,
            "rationale_must_be_non_empty": True,
            "paper_only_scope_must_be_true": True,
            "real_shadow_still_required_before_tiny_canary_or_live_must_be_true": True,
            "no_live_order_sent_must_be_true": True,
            "accepted_status_values": list(template.get("required_decision_values") or []),
        },
        "validation_command_template": (
            ".venv/bin/python scripts/run_market_state_rotation_v6_meta_router_promotion_gate.py "
            "--conditional-overfit-operator-review-report <conditional_overfit_operator_review_report.json> "
            f"--expected-operator-lineage-source-report {expected_source_arg}"
        ),
        "validation_contract": {
            "purpose": "validate_conditional_overfit_operator_review_before_paper_candidate_activation",
            "expected_operator_lineage_source_report": source_report,
            "expected_operator_review_status_path": "conditional_overfit_operator_review.operator_review.status",
            "expected_no_live_order_sent": True,
            "write_report_required_for_validation": False,
            "paper_only_scope": True,
            "real_shadow_still_required_before_tiny_canary_or_live": True,
            "order_submission_allowed": False,
        },
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _candidate_switch_policy_for_promotion(
    *,
    compare_policy: dict[str, Any],
    promotion_decision: str,
    readiness: dict[str, Any],
    operator_lineage_review: dict[str, Any] | None = None,
    generated_at: datetime,
    expected_operator_lineage_source_report: str | None = None,
) -> dict[str, Any]:
    policy = dict(compare_policy or {})
    if not policy:
        return {
            "status": "unavailable",
            "auto_switch_allowed_now": False,
            "blockers": ["candidate_switch_policy_missing"],
            "no_live_order_sent": True,
        }
    blockers = list(readiness.get("blockers") or [])
    execution_parity = dict(readiness.get("execution_parity") or {})
    defensive_candidate = dict(policy.get("defensive_candidate") or {})
    defensive_lineage_review = dict(policy.get("defensive_lineage_review") or {})
    if not defensive_lineage_review and defensive_candidate:
        guard_status = defensive_candidate.get("lineage_guard_status")
        drift_count = int(defensive_candidate.get("lineage_unresolved_material_drift_count") or 0)
        review_required = bool(guard_status and guard_status != "pass") or drift_count > 0
        defensive_lineage_review = {
            "required": review_required,
            "status": "pending_operator_lineage_review" if review_required else "not_required",
            "guard_status": guard_status,
            "unresolved_material_drift_count": drift_count,
            "unresolved_material_folds": list(
                defensive_candidate.get("lineage_unresolved_material_folds") or []
            ),
            "blockers": (
                ["defensive_unresolved_material_drift"] if drift_count > 0 else []
            ),
        }
    defensive_lineage_review = _apply_operator_lineage_review(
        defensive_lineage_review=defensive_lineage_review,
        defensive_candidate=defensive_candidate,
        operator_lineage_review=operator_lineage_review,
        promotion_gate_generated_at=generated_at,
        expected_source_promotion_gate_report=expected_operator_lineage_source_report,
    )
    readiness_ready = bool(readiness.get("ready_for_paper"))
    parity_passed = bool(execution_parity.get("passed"))
    lineage_review_required = bool(defensive_lineage_review.get("required"))
    lineage_review_passed = (
        not lineage_review_required
        or defensive_lineage_review.get("status") in ACCEPTED_LINEAGE_REVIEW_STATUSES
    )
    can_route_defensive = (
        defensive_candidate
        and readiness_ready
        and parity_passed
        and lineage_review_passed
        and promotion_decision
        in {
            "tiny_canary_gate_passed_manual_approval_required",
            "full_live_gate_passed_manual_approval_required",
            "paper_ready_with_readiness_warnings",
        }
    )
    promotion_blockers: list[str] = []
    if not defensive_candidate:
        promotion_blockers.append("defensive_candidate_missing")
    if not readiness_ready:
        promotion_blockers.append("paper_readiness_not_passed")
    if not parity_passed:
        promotion_blockers.append("execution_parity_not_passed")
    if not lineage_review_passed:
        promotion_blockers.append("defensive_lineage_review_not_passed")
        promotion_blockers.extend(str(item) for item in defensive_lineage_review.get("blockers") or [])
    if blockers:
        promotion_blockers.extend(str(item) for item in blockers)
    if can_route_defensive:
        status = "candidate_switch_ready_for_operator_review"
    elif readiness_ready and parity_passed and not lineage_review_passed:
        status = "candidate_switch_blocked_pending_defensive_lineage_review"
    else:
        status = "candidate_switch_blocked_pending_readiness_or_parity"
    return {
        **policy,
        "status": status,
        "defensive_lineage_review": defensive_lineage_review,
        "auto_switch_allowed_now": False,
        "defensive_route_eligible_after_current_gates": can_route_defensive,
        "promotion_decision": promotion_decision,
        "readiness_ready_for_paper": readiness_ready,
        "execution_parity_passed": parity_passed,
        "defensive_lineage_review_required": lineage_review_required,
        "defensive_lineage_review_passed": lineage_review_passed,
        "promotion_blockers": sorted(set(promotion_blockers)),
        "next_action": (
            "operator_review_primary_vs_defensive_route"
            if can_route_defensive
            else (
                "review_defensive_lineage_delta_before_operator_route_selection"
                if readiness_ready and parity_passed and not lineage_review_passed
                else "keep_primary_candidate_default_until_readiness_execution_parity_and_lineage_review_pass"
            )
        ),
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _promotion_decision(
    *,
    candidate: dict[str, Any],
    readiness: dict[str, Any],
    readiness_alignment: dict[str, Any],
    conditional_overfit_holdout_audit: dict[str, Any] | None = None,
    conditional_overfit_operator_review: dict[str, Any] | None = None,
) -> tuple[str, list[str], list[str]]:
    candidate_decision = str(candidate.get("decision") or "")
    overfit_audit = dict(candidate.get("overfit_audit") or {})
    overfit_blockers = list(overfit_audit.get("blockers") or [])
    conditional_holdout = dict(conditional_overfit_holdout_audit or {})
    conditional_review = dict(conditional_overfit_operator_review or {})
    conditional_overfit_paper_reviewed = (
        bool(overfit_blockers)
        and conditional_holdout.get("proxy_passed") is True
        and conditional_review.get("accepted_for_paper_only") is True
    )
    readiness_stage = str(readiness.get("stage") or "unknown")
    blockers = list(readiness.get("blockers") or [])
    warnings = list(readiness.get("warnings") or [])
    execution_parity = dict(readiness.get("execution_parity") or {})

    if candidate_decision != "promotion_candidate_after_formal_wfo":
        return (
            "blocked_no_formal_wfo_promotion_candidate",
            ["best_candidate_is_not_formal_promotion_candidate"],
            ["run_or_fix_formal_shadow_wfo_before_readiness_promotion"],
        )

    if overfit_blockers and not conditional_overfit_paper_reviewed:
        return (
            "blocked_pending_overfit_holdout_review",
            [str(item) for item in overfit_blockers],
            ["run_or_attach_independent_shadow_holdout_before_paper_or_live_promotion"],
        )

    if not bool(readiness_alignment.get("passed")):
        return (
            "blocked_readiness_candidate_mismatch",
            list(readiness_alignment.get("blockers") or ["readiness_candidate_alignment_failed"]),
            ["rerun_live_readiness_for_the_current_best_candidate_report"],
        )

    if bool(readiness.get("ready_for_full_live")) and conditional_overfit_paper_reviewed:
        return (
            "paper_ready_conditional_overfit_reviewed_pending_real_shadow_for_canary",
            [
                "formal_wfo_passed",
                "conditional_overfit_proxy_and_operator_review_passed_for_paper_only",
                "real_shadow_holdout_required_before_tiny_canary_or_full_live",
            ],
            ["complete_real_shadow_holdout_before_tiny_canary_or_full_live"],
        )

    if bool(readiness.get("ready_for_full_live")):
        return (
            "full_live_gate_passed_manual_approval_required",
            ["formal_wfo_and_readiness_passed"],
            ["keep_live_disabled_until_explicit_manual_launch_approval"],
        )

    if bool(readiness.get("ready_for_tiny_canary")) and conditional_overfit_paper_reviewed:
        return (
            "paper_ready_conditional_overfit_reviewed_pending_real_shadow_for_canary",
            [
                "formal_wfo_passed",
                "conditional_overfit_proxy_and_operator_review_passed_for_paper_only",
                "real_shadow_holdout_required_before_tiny_canary_or_full_live",
            ],
            ["complete_real_shadow_holdout_before_tiny_canary_or_full_live"],
        )

    if bool(readiness.get("ready_for_tiny_canary")):
        return (
            "tiny_canary_gate_passed_manual_approval_required",
            ["formal_wfo_passed_and_tiny_canary_readiness_passed"],
            ["keep_live_disabled_until_explicit_manual_canary_approval"],
        )

    if bool(readiness.get("ready_for_paper")):
        parity_missing = "live_or_paper_execution_parity_available" in blockers
        parity_passed = bool(execution_parity.get("passed"))
        if parity_missing and not parity_passed:
            parity_available = bool(execution_parity.get("available"))
            parity_reason = "execution_parity_not_passed" if parity_available else "execution_parity_missing"
            reasons = ["formal_wfo_passed", "paper_readiness_passed", parity_reason]
            next_actions = ["collect_paper_execution_parity_rows_before_tiny_canary_or_full_live"]
            if conditional_overfit_paper_reviewed:
                reasons.append("conditional_overfit_review_accepted_for_paper_only")
                next_actions.append("complete_real_shadow_holdout_before_tiny_canary_or_full_live")
            return (
                "paper_ready_pending_execution_parity",
                reasons,
                next_actions,
            )
        reasons = ["formal_wfo_passed", "paper_readiness_passed", "warnings_or_noncritical_blockers_present"]
        next_actions = ["review_readiness_warnings_before_any_canary"]
        if conditional_overfit_paper_reviewed:
            reasons.append("conditional_overfit_review_accepted_for_paper_only")
            next_actions.append("complete_real_shadow_holdout_before_tiny_canary_or_full_live")
        return (
            "paper_ready_with_readiness_warnings",
            reasons,
            next_actions,
        )

    if blockers:
        return (
            "research_only_until_readiness_blockers_resolved",
            ["readiness_blockers_present"],
            ["resolve_readiness_blockers_before_paper_or_live_promotion"],
        )

    if warnings:
        return (
            "research_only_until_readiness_warnings_reviewed",
            ["readiness_warnings_present"],
            ["review_and_accept_or_fix_readiness_warnings_before_promotion"],
        )

    return (
        "research_only_unknown_readiness_state",
        ["readiness_state_inconclusive"],
        ["inspect_readiness_report_manually"],
    )


def build_meta_router_promotion_gate(
    *,
    compare_report: dict[str, Any],
    readiness_report: dict[str, Any],
    operator_lineage_review_report: dict[str, Any] | None = None,
    conditional_overfit_operator_review_report: dict[str, Any] | None = None,
    conditional_overfit_holdout_audit_report: dict[str, Any] | None = None,
    input_compare_report: str | None = None,
    input_readiness_report: str | None = None,
    input_operator_lineage_review_report: str | None = None,
    input_conditional_overfit_operator_review_report: str | None = None,
    input_conditional_overfit_holdout_audit_report: str | None = None,
    expected_operator_lineage_source_report: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    candidate = dict(compare_report.get("best_candidate") or {})
    candidate_metrics = dict(candidate.get("candidate") or {})
    overfit_audit = dict(candidate.get("overfit_audit") or {})
    mode_summary = dict(candidate_metrics.get("router_mode_summary") or {})
    execution_parity = dict(readiness_report.get("execution_parity") or {})
    execution_change_audit = _candidate_execution_change_audit(
        candidate_metrics=candidate_metrics,
        compare_candidate=candidate,
    )
    readiness_alignment = _readiness_candidate_alignment(
        candidate=candidate,
        readiness=readiness_report,
    )
    conditional_overfit_holdout_audit = _conditional_overfit_holdout_audit_summary(
        candidate=candidate,
        audit_report=conditional_overfit_holdout_audit_report,
        input_report=input_conditional_overfit_holdout_audit_report,
    )
    conditional_overfit_operator_review = _apply_conditional_overfit_operator_review(
        candidate=candidate,
        overfit_audit=overfit_audit,
        conditional_holdout=conditional_overfit_holdout_audit,
        operator_review_report=conditional_overfit_operator_review_report,
        promotion_gate_generated_at=generated_at,
        expected_source_promotion_gate_report=expected_operator_lineage_source_report,
    )
    decision, reasons, next_actions = _promotion_decision(
        candidate=candidate,
        readiness=readiness_report,
        readiness_alignment=readiness_alignment,
        conditional_overfit_holdout_audit=conditional_overfit_holdout_audit,
        conditional_overfit_operator_review=conditional_overfit_operator_review,
    )
    if (
        decision == "blocked_pending_overfit_holdout_review"
        and conditional_overfit_holdout_audit.get("proxy_passed") is True
    ):
        next_actions = list(next_actions) + [
            "historical_proxy_attached_but_real_shadow_or_operator_review_still_required"
        ]
    readiness_blockers = list(readiness_report.get("blockers") or [])
    compare_summary = {
        "performance_upgrade_status": compare_report.get("performance_upgrade_status"),
        "performance_upgrade_candidate_count": int(
            compare_report.get("performance_upgrade_candidate_count") or 0
        ),
        "performance_upgrade_smoke_candidate_count": int(
            compare_report.get("performance_upgrade_smoke_candidate_count") or 0
        ),
        "risk_compression_status": compare_report.get("risk_compression_status"),
        "risk_compression_candidate_count": int(compare_report.get("risk_compression_candidate_count") or 0),
        "risk_compression_smoke_candidate_count": int(
            compare_report.get("risk_compression_smoke_candidate_count") or 0
        ),
        "risk_compression_formal_tradeoff_count": int(
            compare_report.get("risk_compression_formal_tradeoff_count") or 0
        ),
        "risk_compression_tradeoff_count": int(compare_report.get("risk_compression_tradeoff_count") or 0),
        "risk_compression_next_action": compare_report.get("risk_compression_next_action"),
        "risk_adjusted_compression_status": compare_report.get("risk_adjusted_compression_status"),
        "risk_adjusted_compression_candidate_count": int(
            compare_report.get("risk_adjusted_compression_candidate_count") or 0
        ),
        "risk_adjusted_compression_smoke_candidate_count": int(
            compare_report.get("risk_adjusted_compression_smoke_candidate_count") or 0
        ),
        "risk_adjusted_compression_next_action": compare_report.get(
            "risk_adjusted_compression_next_action"
        ),
        "best_performance_upgrade_candidate": _compare_candidate_summary(
            compare_report.get("best_performance_upgrade_candidate")
        ),
        "best_performance_upgrade_smoke_candidate": _compare_candidate_summary(
            compare_report.get("best_performance_upgrade_smoke_candidate")
        ),
        "best_risk_compression_candidate": _compare_candidate_summary(
            compare_report.get("best_risk_compression_candidate")
        ),
        "best_risk_compression_smoke_candidate": _compare_candidate_summary(
            compare_report.get("best_risk_compression_smoke_candidate")
        ),
        "best_risk_compression_tradeoff": _compare_candidate_summary(
            compare_report.get("best_risk_compression_tradeoff")
        ),
        "best_risk_adjusted_compression_candidate": _compare_candidate_summary(
            compare_report.get("best_risk_adjusted_compression_candidate")
        ),
        "best_risk_adjusted_compression_smoke_candidate": _compare_candidate_summary(
            compare_report.get("best_risk_adjusted_compression_smoke_candidate")
        ),
        "candidate_switch_policy": dict(compare_report.get("candidate_switch_policy") or {}),
    }
    candidate_switch_policy = _candidate_switch_policy_for_promotion(
        compare_policy=dict(compare_report.get("candidate_switch_policy") or {}),
        promotion_decision=decision,
        readiness=readiness_report,
        operator_lineage_review=operator_lineage_review_report,
        generated_at=generated_at,
        expected_operator_lineage_source_report=expected_operator_lineage_source_report,
    )
    next_blocker = None
    alignment_blockers = list(readiness_alignment.get("blockers") or [])
    if decision == "blocked_pending_overfit_holdout_review" and reasons:
        next_blocker = str(reasons[0])
    elif alignment_blockers:
        next_blocker = str(alignment_blockers[0])
    else:
        next_blocker = _first_blocker(readiness_report)

    return {
        "generated_at": generated_at.isoformat(),
        "status": "meta_router_promotion_gate_complete",
        "no_live_order_sent": True,
        "input_compare_report": input_compare_report,
        "input_readiness_report": input_readiness_report,
        "input_operator_lineage_review_report": input_operator_lineage_review_report,
        "input_conditional_overfit_operator_review_report": input_conditional_overfit_operator_review_report,
        "input_conditional_overfit_holdout_audit_report": input_conditional_overfit_holdout_audit_report,
        "expected_operator_lineage_source_report": expected_operator_lineage_source_report,
        "safety_policy": {
            "research_or_paper_only": True,
            "live_orders_enabled": False,
            "manual_approval_required_before_any_live_or_canary": True,
        },
        "promotion_decision": decision,
        "decision_reasons": reasons,
        "next_actions": next_actions,
        "next_blocker": next_blocker,
        "performance_upgrade_ready": bool(execution_change_audit.get("performance_upgrade_ready")),
        "performance_delta_status": execution_change_audit.get("status"),
        "performance_upgrade_blockers": list(execution_change_audit.get("blockers") or []),
        "performance_upgrade_notes": list(execution_change_audit.get("notes") or []),
        "overfit_audit": overfit_audit,
        "overfit_blockers": list(overfit_audit.get("blockers") or []),
        "conditional_overfit_holdout_audit": conditional_overfit_holdout_audit,
        "conditional_overfit_operator_review": conditional_overfit_operator_review,
        "risk_compression_ready": bool(execution_change_audit.get("risk_compression_ready")),
        "risk_compression_detected": bool(execution_change_audit.get("risk_compression_detected")),
        "risk_adjusted_compression_ready": bool(
            execution_change_audit.get("risk_adjusted_compression_ready")
        ),
        "risk_compression_blockers": [
            item
            for item in list(execution_change_audit.get("blockers") or [])
            if str(item).startswith("risk_compression")
        ],
        "compare_summary": compare_summary,
        "candidate_switch_policy": candidate_switch_policy,
        "readiness_candidate_alignment": readiness_alignment,
        "candidate": {
            "recipe_id": candidate.get("recipe_id"),
            "decision": candidate.get("decision"),
            "report_path": candidate.get("report_path"),
            "lineage": dict(candidate.get("lineage") or {}),
            "fold_count": int(candidate_metrics.get("fold_count") or 0),
            "compounded_return_pct": _pct(candidate_metrics.get("compounded_return_pct")),
            "min_return_pct": _pct(candidate_metrics.get("min_return_pct")),
            "max_drawdown_pct": _pct(candidate_metrics.get("max_drawdown_pct")),
            "avg_cost_drag_pct": _pct(candidate_metrics.get("avg_cost_drag_pct")),
            "trade_like_events": int(candidate_metrics.get("trade_like_events") or 0),
            "return_delta_vs_baseline_pct": _pct(candidate_metrics.get("return_delta_vs_baseline_pct")),
            "drawdown_delta_vs_baseline_pct": _pct(candidate_metrics.get("drawdown_delta_vs_baseline_pct")),
            "cost_delta_vs_baseline_pct": _pct(candidate_metrics.get("cost_delta_vs_baseline_pct")),
            "trade_event_delta_vs_baseline": int(candidate_metrics.get("trade_event_delta_vs_baseline") or 0),
            "execution_change_audit": execution_change_audit,
            "overfit_audit": overfit_audit,
            "router_modes": mode_summary,
        },
        "readiness": {
            "stage": readiness_report.get("stage"),
            "ready_for_paper": bool(readiness_report.get("ready_for_paper")),
            "ready_for_tiny_canary": bool(readiness_report.get("ready_for_tiny_canary")),
            "ready_for_full_live": bool(readiness_report.get("ready_for_full_live")),
            "blockers": readiness_blockers,
            "warnings": list(readiness_report.get("warnings") or []),
            "stage_blockers": dict(readiness_report.get("stage_blockers") or {}),
            "deployment_limits": dict(readiness_report.get("deployment_limits") or {}),
            "execution_parity": execution_parity,
            "time_substitution_policy": dict(readiness_report.get("time_substitution_policy") or {}),
            "upgrade_backlog": dict(readiness_report.get("upgrade_backlog") or {}),
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    candidate = dict(report.get("candidate") or {})
    readiness = dict(report.get("readiness") or {})
    alignment = dict(report.get("readiness_candidate_alignment") or {})
    execution_audit = dict(candidate.get("execution_change_audit") or {})
    overfit_audit = dict(candidate.get("overfit_audit") or {})
    conditional_holdout = dict(report.get("conditional_overfit_holdout_audit") or {})
    conditional_overfit_review = dict(report.get("conditional_overfit_operator_review") or {})
    conditional_overfit_review_operator = dict(conditional_overfit_review.get("operator_review") or {})
    conditional_overfit_review_template = dict(conditional_overfit_review.get("operator_review_template") or {})
    conditional_holdout_tail = dict(conditional_holdout.get("tail_holdout_proxy") or {})
    conditional_holdout_delta = dict(conditional_holdout.get("aggregate_delta") or {})
    compare_summary = dict(report.get("compare_summary") or {})
    risk_tradeoff = dict(compare_summary.get("best_risk_compression_tradeoff") or {})
    risk_adjusted = dict(compare_summary.get("best_risk_adjusted_compression_candidate") or {})
    switch_policy = dict(report.get("candidate_switch_policy") or {})
    defensive_lineage_review = dict(switch_policy.get("defensive_lineage_review") or {})
    defensive_operator_review = dict(defensive_lineage_review.get("operator_review") or {})
    defensive_operator_template = dict(defensive_lineage_review.get("operator_review_template") or {})
    limits = dict(readiness.get("deployment_limits") or {})
    return "\n".join(
        [
            "# Market State Rotation V6 Meta-Router Promotion Gate",
            "",
            f"- status: `{report.get('status')}`",
            f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
            f"- promotion_decision: `{report.get('promotion_decision')}`",
            f"- next_blocker: `{report.get('next_blocker')}`",
            f"- performance_upgrade_ready: `{report.get('performance_upgrade_ready')}`",
            f"- performance_delta_status: `{report.get('performance_delta_status')}`",
            f"- performance_upgrade_blockers: `{', '.join(report.get('performance_upgrade_blockers') or [])}`",
            f"- overfit_audit_status: `{overfit_audit.get('status')}`",
            f"- overfit_blockers: `{', '.join(report.get('overfit_blockers') or [])}`",
            f"- conditional_overfit_holdout_status: `{conditional_holdout.get('status')}`",
            f"- conditional_overfit_holdout_proxy_passed: `{conditional_holdout.get('proxy_passed')}`",
            f"- conditional_overfit_holdout_real_shadow_required: `{conditional_holdout.get('real_shadow_still_required')}`",
            f"- conditional_overfit_holdout_tail_delta_pct: `{conditional_holdout_tail.get('return_delta_pct')}`",
            f"- conditional_overfit_holdout_aggregate_delta_pct: `{conditional_holdout_delta.get('return_delta_pct')}`",
            f"- conditional_overfit_holdout_warnings: `{', '.join(conditional_holdout.get('warnings') or [])}`",
            f"- conditional_overfit_operator_review_status: `{conditional_overfit_review.get('status')}`",
            f"- conditional_overfit_operator_review_accepted_for_paper_only: `{conditional_overfit_review.get('accepted_for_paper_only')}`",
            f"- conditional_overfit_operator_review_blockers: `{', '.join(conditional_overfit_review.get('blockers') or [])}`",
            f"- conditional_overfit_operator_review_report_status: `{conditional_overfit_review_operator.get('status')}`",
            f"- conditional_overfit_operator_review_template_candidate: `{conditional_overfit_review_template.get('candidate_recipe_id')}`",
            f"- conditional_overfit_operator_review_template_fingerprint: `{conditional_overfit_review_template.get('review_packet_fingerprint')}`",
            f"- conditional_overfit_operator_review_template_report: `{report.get('conditional_overfit_operator_review_template_report')}`",
            f"- conditional_overfit_operator_review_skeleton_report: `{report.get('conditional_overfit_operator_review_skeleton_report')}`",
            f"- compare_performance_upgrade_status: `{compare_summary.get('performance_upgrade_status')}`",
            f"- risk_compression_ready: `{report.get('risk_compression_ready')}`",
            f"- risk_compression_blockers: `{', '.join(report.get('risk_compression_blockers') or [])}`",
            f"- compare_risk_compression_status: `{compare_summary.get('risk_compression_status')}`",
            f"- compare_risk_compression_next_action: `{compare_summary.get('risk_compression_next_action')}`",
            f"- compare_best_risk_compression_tradeoff: `{risk_tradeoff.get('recipe_id')}`",
            f"- compare_best_risk_compression_tradeoff_deltas: `{risk_tradeoff.get('return_delta_vs_baseline_pct')}` / `{risk_tradeoff.get('drawdown_delta_vs_baseline_pct')}` / `{risk_tradeoff.get('cost_delta_vs_baseline_pct')}`",
            f"- compare_risk_adjusted_compression_status: `{compare_summary.get('risk_adjusted_compression_status')}`",
            f"- compare_risk_adjusted_compression_next_action: `{compare_summary.get('risk_adjusted_compression_next_action')}`",
            f"- compare_best_risk_adjusted_compression: `{risk_adjusted.get('recipe_id')}`",
            f"- compare_best_risk_adjusted_compression_deltas: `{risk_adjusted.get('return_delta_vs_baseline_pct')}` / `{risk_adjusted.get('drawdown_delta_vs_baseline_pct')}` / `{risk_adjusted.get('cost_delta_vs_baseline_pct')}`",
            f"- candidate_switch_policy_status: `{switch_policy.get('status')}`",
            f"- candidate_switch_default_route: `{switch_policy.get('default_route')}`",
            f"- candidate_switch_defensive_route: `{switch_policy.get('defensive_route')}`",
            f"- candidate_switch_defensive_lineage_review_status: `{defensive_lineage_review.get('status')}`",
            f"- candidate_switch_defensive_lineage_operator_review_status: `{defensive_operator_review.get('status')}`",
            f"- candidate_switch_defensive_lineage_template_candidate: `{defensive_operator_template.get('candidate_recipe_id')}`",
            f"- candidate_switch_defensive_lineage_template_folds: `{defensive_operator_template.get('reviewed_folds')}`",
            f"- candidate_switch_defensive_lineage_template_summary: `{defensive_operator_template.get('review_packet_summary')}`",
            f"- candidate_switch_defensive_lineage_template_fingerprint: `{defensive_operator_template.get('review_packet_fingerprint')}`",
            f"- operator_lineage_review_template_report: `{report.get('operator_lineage_review_template_report')}`",
            f"- operator_lineage_review_skeleton_report: `{report.get('operator_lineage_review_skeleton_report')}`",
            f"- candidate_switch_blockers: `{', '.join(switch_policy.get('promotion_blockers') or [])}`",
            f"- candidate: `{candidate.get('recipe_id')}` / `{candidate.get('decision')}`",
            f"- readiness candidate alignment: `{alignment.get('passed')}`",
            f"- return/DD/cost: `{candidate.get('compounded_return_pct')}` / `{candidate.get('max_drawdown_pct')}` / `{candidate.get('avg_cost_drag_pct')}`",
            f"- return/DD/cost/trade deltas: `{execution_audit.get('return_delta_vs_baseline_pct')}` / `{execution_audit.get('drawdown_delta_vs_baseline_pct')}` / `{execution_audit.get('cost_delta_vs_baseline_pct')}` / `{execution_audit.get('trade_event_delta_vs_baseline')}`",
            f"- readiness stage: `{readiness.get('stage')}`",
            f"- readiness blockers: `{', '.join(readiness.get('blockers') or [])}`",
            f"- readiness warnings: `{', '.join(readiness.get('warnings') or [])}`",
            f"- recommended max size multiplier: `{limits.get('recommended_max_size_multiplier')}`",
            f"- recommended effective leverage cap: `{limits.get('recommended_effective_leverage_cap')}`",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate v6 meta-router formal WFO candidate against readiness.")
    parser.add_argument("--compare-report", default=DEFAULT_COMPARE_REPORT)
    parser.add_argument("--readiness-report", default=DEFAULT_READINESS_REPORT)
    parser.add_argument(
        "--conditional-overfit-holdout-audit-report",
        default=DEFAULT_CONDITIONAL_OVERFIT_HOLDOUT_AUDIT_REPORT,
    )
    parser.add_argument("--operator-lineage-review-report")
    parser.add_argument("--conditional-overfit-operator-review-report")
    parser.add_argument("--expected-operator-lineage-source-report")
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_dir = _resolve(args.report_dir)
    json_path = report_dir / "market_state_rotation_v6_meta_router_promotion_gate.json"
    expected_operator_lineage_source_report = (
        _display_path(args.expected_operator_lineage_source_report)
        if args.expected_operator_lineage_source_report
        else _display_path(json_path)
    )
    report = build_meta_router_promotion_gate(
        compare_report=_load_json(args.compare_report),
        readiness_report=_load_json(args.readiness_report),
        operator_lineage_review_report=(
            _load_json(args.operator_lineage_review_report)
            if args.operator_lineage_review_report
            else None
        ),
        conditional_overfit_operator_review_report=(
            _load_json(args.conditional_overfit_operator_review_report)
            if args.conditional_overfit_operator_review_report
            else None
        ),
        conditional_overfit_holdout_audit_report=_load_optional_json(
            args.conditional_overfit_holdout_audit_report
        ),
        input_compare_report=_display_path(args.compare_report),
        input_readiness_report=_display_path(args.readiness_report),
        input_operator_lineage_review_report=_display_path(args.operator_lineage_review_report),
        input_conditional_overfit_operator_review_report=_display_path(
            args.conditional_overfit_operator_review_report
        ),
        input_conditional_overfit_holdout_audit_report=_display_path(
            args.conditional_overfit_holdout_audit_report
        ),
        expected_operator_lineage_source_report=expected_operator_lineage_source_report,
    )
    if args.write_report:
        assert report_dir is not None
        report_dir.mkdir(parents=True, exist_ok=True)
        assert json_path is not None
        md_path = report_dir / "market_state_rotation_v6_meta_router_promotion_gate.md"
        report["report_path"] = _display_path(json_path)
        template_report = _operator_lineage_review_template_report(
            report=report,
            source_promotion_gate_report=json_path,
        )
        conditional_overfit_template_report = _conditional_overfit_operator_review_template_report(
            report=report,
            source_promotion_gate_report=json_path,
        )
        if template_report is not None:
            template_path = report_dir / "market_state_rotation_v6_operator_lineage_review_template.json"
            skeleton_path = report_dir / "market_state_rotation_v6_operator_lineage_review_skeleton.json"
            skeleton_report = dict(template_report.get("operator_review_json_skeleton") or {})
            skeleton_report.update(
                {
                    "skeleton_report_path": _display_path(skeleton_path),
                    "source_template_report": _display_path(template_path),
                    "validation_command_template": template_report.get("validation_command_template"),
                    "validation_contract": dict(template_report.get("validation_contract") or {}),
                }
            )
            template_report["template_report_path"] = _display_path(template_path)
            template_report["operator_review_json_skeleton_report"] = _display_path(skeleton_path)
            report["operator_lineage_review_template_report"] = _display_path(template_path)
            report["operator_lineage_review_skeleton_report"] = _display_path(skeleton_path)
            report["operator_lineage_artifact_manifest"] = {
                "fingerprint_algorithm": "sha256_canonical_json",
                "template_report": _display_path(template_path),
                "template_payload_fingerprint": _fingerprint_payload(template_report),
                "skeleton_report": _display_path(skeleton_path),
                "skeleton_payload_fingerprint": _fingerprint_payload(skeleton_report),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
            template_path.write_text(
                json.dumps(template_report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            skeleton_path.write_text(
                json.dumps(skeleton_report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if conditional_overfit_template_report is not None:
            template_path = report_dir / "market_state_rotation_v6_conditional_overfit_operator_review_template.json"
            skeleton_path = report_dir / "market_state_rotation_v6_conditional_overfit_operator_review_skeleton.json"
            skeleton_report = dict(
                conditional_overfit_template_report.get("operator_review_json_skeleton") or {}
            )
            skeleton_report.update(
                {
                    "skeleton_report_path": _display_path(skeleton_path),
                    "source_template_report": _display_path(template_path),
                    "validation_command_template": conditional_overfit_template_report.get(
                        "validation_command_template"
                    ),
                    "validation_contract": dict(
                        conditional_overfit_template_report.get("validation_contract") or {}
                    ),
                }
            )
            conditional_overfit_template_report["template_report_path"] = _display_path(template_path)
            conditional_overfit_template_report["operator_review_json_skeleton_report"] = _display_path(
                skeleton_path
            )
            report["conditional_overfit_operator_review_template_report"] = _display_path(template_path)
            report["conditional_overfit_operator_review_skeleton_report"] = _display_path(skeleton_path)
            report["conditional_overfit_operator_review_artifact_manifest"] = {
                "fingerprint_algorithm": "sha256_canonical_json",
                "template_report": _display_path(template_path),
                "template_payload_fingerprint": _fingerprint_payload(conditional_overfit_template_report),
                "skeleton_report": _display_path(skeleton_path),
                "skeleton_payload_fingerprint": _fingerprint_payload(skeleton_report),
                "paper_only_scope": True,
                "real_shadow_still_required_before_tiny_canary_or_live": True,
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
            template_path.write_text(
                json.dumps(conditional_overfit_template_report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            skeleton_path.write_text(
                json.dumps(skeleton_report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
        if template_report is not None:
            print(f"wrote {report.get('operator_lineage_review_template_report')}")
            print(f"wrote {report.get('operator_lineage_review_skeleton_report')}")
        if conditional_overfit_template_report is not None:
            print(f"wrote {report.get('conditional_overfit_operator_review_template_report')}")
            print(f"wrote {report.get('conditional_overfit_operator_review_skeleton_report')}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
