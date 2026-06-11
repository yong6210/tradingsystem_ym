#!/usr/bin/env python3
"""Gate near-miss smoke candidates across multiple validation windows."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


DEFAULT_SMOKE_REPORTS = (
    "reports/validation/diagnostics/market_state_rotation_v6_near_miss_smoke_quality_gated_mc12_check/"
    "market_state_rotation_v6_near_miss_smoke.json,"
    "reports/validation/diagnostics/market_state_rotation_v6_near_miss_smoke_quality_gated_mc12_365d_check/"
    "market_state_rotation_v6_near_miss_smoke.json"
)
DEFAULT_FULL_WALK_FORWARD_GATE_REPORT = (
    "reports/validation/diagnostics/"
    "market_state_rotation_v6_quality_gated_mc12_near_miss_full_wf_pure_gate_vs_current_meta_router/"
    "market_state_rotation_v6_full_walk_forward_gate.json,"
    "reports/validation/diagnostics/"
    "market_state_rotation_v6_quality_gated_mc12_score5_edge3_stack2_ext10_full_wf_pure_gate_vs_current_meta_router/"
    "market_state_rotation_v6_full_walk_forward_gate.json,"
    "reports/validation/diagnostics/"
    "market_state_rotation_v6_quality_gated_mc12_score5_edge2_stack2_ext10_full_wf_pure_gate_vs_current_meta_router/"
    "market_state_rotation_v6_full_walk_forward_gate.json,"
    "reports/validation/diagnostics/"
    "market_state_rotation_v6_quality_gated_mc12_downtrend_score5_edge2_stack2_ext10_full_wf_pure_gate_vs_current_meta_router/"
    "market_state_rotation_v6_full_walk_forward_gate.json,"
    "reports/validation/diagnostics/"
    "market_state_rotation_v6_seeded_mc12_downtrend_score4_edge2_stack2_ext10_cooldown72_react200cap_mdd20p01_strict_activity_gate/"
    "market_state_rotation_v6_full_walk_forward_gate.json"
)


def _resolve(path: str | Path) -> Path:
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _candidate_rows(smoke_report: dict[str, Any], *, input_report: str) -> list[dict[str, Any]]:
    window = dict(smoke_report.get("window") or {})
    rows: list[dict[str, Any]] = []
    for item in list(smoke_report.get("candidates") or []):
        if item.get("name") == "base":
            continue
        delta = dict(item.get("delta_vs_base") or {})
        rows.append(
            {
                "name": item.get("name"),
                "input_report": input_report,
                "window_days": _int(window.get("days")),
                "return_pct": _float(item.get("total_return_pct")),
                "max_drawdown_pct": _float(item.get("max_drawdown_pct")),
                "trade_like_events": _int(item.get("trade_like_events")),
                "add_events": _int(item.get("add_events")),
                "probe_adds": _int(item.get("probe_adds")),
                "add_by_role": dict(item.get("add_by_role") or {}),
                "activity_non_regression_contract": dict(
                    item.get("activity_non_regression_contract") or {}
                ),
                "primary_use": item.get("primary_use"),
                "smoke_decision": item.get("smoke_decision"),
                "config_change": dict(item.get("config_change") or {}),
                "delta_return_pct": _float(delta.get("return_pct")),
                "delta_max_drawdown_pct": _float(delta.get("max_drawdown_pct")),
                "delta_add_events": _int(delta.get("add_events")),
                "delta_trade_like_events": _int(delta.get("trade_like_events")),
                "delta_probe_adds": _int(delta.get("probe_adds")),
            }
        )
    return rows


def _csv_or_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _safety_blockers(row: dict[str, Any]) -> list[str]:
    config = dict(row.get("config_change") or {})
    blockers: list[str] = []
    units = _float(config.get("near_miss_probe_units"))
    if units <= 0.0:
        blockers.append("near_miss_probe_units_missing_or_disabled")
    elif units > 0.00025:
        blockers.append("near_miss_probe_units_above_0_00025")
    if _int(config.get("near_miss_probe_min_score")) < 4:
        blockers.append("near_miss_probe_min_score_below_4")
    if _int(config.get("near_miss_probe_min_score_edge")) < 2:
        blockers.append("near_miss_probe_min_score_edge_below_2")
    if _int(config.get("near_miss_probe_min_reason_stack")) < 2:
        blockers.append("near_miss_probe_min_reason_stack_below_2")
    if _float(config.get("near_miss_probe_max_extension_atr")) > 1.5:
        blockers.append("near_miss_probe_max_extension_atr_above_1_5")
    allowed_reasons = set(_csv_or_list(config.get("near_miss_probe_allowed_soft_reasons")))
    if not allowed_reasons:
        blockers.append("near_miss_probe_allowed_soft_reasons_missing")
    if allowed_reasons - {"MC12_low_confluence"}:
        blockers.append("near_miss_probe_allows_non_mc12_soft_reasons")
    if "MC04_no_clear_first_touch" in allowed_reasons:
        blockers.append("near_miss_probe_allows_mc04_broad_first_touch")
    return blockers


def _count_safety_blockers(candidate_reports: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidate_reports:
        for window in list(candidate.get("safety_blockers_by_window") or []):
            for blocker in list(dict(window).get("blockers") or []):
                key = str(blocker)
                counts[key] = counts.get(key, 0) + 1
    priority = {
        "near_miss_probe_allowed_soft_reasons_missing": 0,
        "near_miss_probe_allows_mc04_broad_first_touch": 1,
        "near_miss_probe_allows_non_mc12_soft_reasons": 2,
        "near_miss_probe_units_above_0_00025": 3,
        "near_miss_probe_min_score_below_4": 4,
        "near_miss_probe_min_score_edge_below_2": 5,
        "near_miss_probe_min_reason_stack_below_2": 6,
        "near_miss_probe_max_extension_atr_above_1_5": 7,
    }
    return dict(sorted(counts.items(), key=lambda item: (-item[1], priority.get(item[0], 999), item[0])))


def _full_walk_forward_gate_summary(gate_report: dict[str, Any] | None) -> dict[str, Any]:
    report = dict(gate_report or {})
    if not report:
        return {
            "available": False,
            "status": "not_available",
            "paper_evidence_collection_allowed": False,
            "paper_or_live_promotion_allowed": False,
            "no_live_order_sent": True,
        }
    failed_checks = [str(item) for item in list(report.get("failed_checks") or []) if str(item)]
    overall_status = str(report.get("overall_status") or "").strip()
    decision = str(report.get("decision") or "").strip()
    gates = dict(report.get("gates") or {})
    activity_regression = dict(report.get("activity_regression_summary") or {})
    strict_activity_gate_present = gates.get("require_nonregressing_activity") is True
    nonregressing_activity_gate_missing = not strict_activity_gate_present
    activity_regression_requires_strict_rerun = (
        nonregressing_activity_gate_missing
        and activity_regression.get("signal_sparsity_fix_failed") is True
    )
    if nonregressing_activity_gate_missing:
        failed_checks.append("full_walk_forward_gate_missing_require_nonregressing_activity")
    if activity_regression_requires_strict_rerun:
        failed_checks.append("activity_regression_requires_nonregressing_gate_rerun")
    failed_checks = list(dict.fromkeys(failed_checks))
    blocked = overall_status == "blocked" or bool(failed_checks)
    paper_evidence_allowed = not blocked and decision == "eligible_for_paper_evidence_collection_only"
    status = (
        "blocked_full_walk_forward_gate"
        if blocked
        else "paper_evidence_collection_candidate_available"
        if paper_evidence_allowed
        else "review_required"
    )
    return {
        "available": True,
        "status": status,
        "generated_at": report.get("generated_at"),
        "candidate_name": report.get("candidate_name"),
        "overall_status": overall_status,
        "decision": decision,
        "gates": gates,
        "strict_activity_gate_required": True,
        "strict_activity_gate_present": strict_activity_gate_present,
        "nonregressing_activity_gate_missing": nonregressing_activity_gate_missing,
        "activity_regression_requires_strict_rerun": activity_regression_requires_strict_rerun,
        "failed_checks": failed_checks,
        "deltas": dict(report.get("deltas") or {}),
        "activity_regression_summary": activity_regression,
        "fold_delta_summary": dict(report.get("fold_delta_summary") or {}),
        "failure_details": dict(report.get("failure_details") or {}),
        "root_cause_hints": list(report.get("root_cause_hints") or []),
        "paper_evidence_collection_allowed": paper_evidence_allowed,
        "paper_or_live_promotion_allowed": False,
        "no_live_order_sent": report.get("no_live_order_sent") is not False,
    }


def _activity_regression_rollup(full_wfo_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for summary in full_wfo_summaries:
        activity = dict(summary.get("activity_regression_summary") or {})
        if not activity:
            continue
        rows.append(
            {
                "candidate_name": summary.get("candidate_name"),
                "status": summary.get("status"),
                "signal_sparsity_fix_failed": bool(activity.get("signal_sparsity_fix_failed")),
                "probe_activity_regressed": bool(activity.get("probe_activity_regressed")),
                "trade_like_activity_regressed": bool(activity.get("trade_like_activity_regressed")),
                "baseline_probe_adds": activity.get("baseline_probe_adds"),
                "candidate_probe_adds": activity.get("candidate_probe_adds"),
                "probe_add_delta": activity.get("probe_add_delta"),
                "probe_add_delta_pct": activity.get("probe_add_delta_pct"),
                "baseline_trade_like_events": activity.get("baseline_trade_like_events"),
                "candidate_trade_like_events": activity.get("candidate_trade_like_events"),
                "trade_like_events_delta": activity.get("trade_like_events_delta"),
                "trade_like_events_delta_pct": activity.get("trade_like_events_delta_pct"),
                "diagnostic_labels": list(activity.get("diagnostic_labels") or []),
            }
        )
    failed_rows = [row for row in rows if row.get("signal_sparsity_fix_failed")]
    probe_regressed_rows = [row for row in rows if row.get("probe_activity_regressed")]
    trade_like_regressed_rows = [row for row in rows if row.get("trade_like_activity_regressed")]
    labels = sorted(
        {
            str(label)
            for row in rows
            for label in list(row.get("diagnostic_labels") or [])
            if str(label)
        }
    )
    worst_probe = min(rows, key=lambda row: _float(row.get("probe_add_delta_pct"), 0.0), default=None)
    worst_trade_like = min(
        rows,
        key=lambda row: _float(row.get("trade_like_events_delta_pct"), 0.0),
        default=None,
    )
    return {
        "available": bool(rows),
        "candidate_count": len(rows),
        "signal_sparsity_fix_failed_candidate_count": len(failed_rows),
        "signal_sparsity_fix_failed_candidate_names": sorted(
            str(row.get("candidate_name")) for row in failed_rows if row.get("candidate_name")
        ),
        "probe_activity_regressed_candidate_count": len(probe_regressed_rows),
        "probe_activity_regressed_candidate_names": sorted(
            str(row.get("candidate_name")) for row in probe_regressed_rows if row.get("candidate_name")
        ),
        "trade_like_activity_regressed_candidate_count": len(trade_like_regressed_rows),
        "trade_like_activity_regressed_candidate_names": sorted(
            str(row.get("candidate_name")) for row in trade_like_regressed_rows if row.get("candidate_name")
        ),
        "diagnostic_labels": labels,
        "worst_probe_add_delta_candidate": worst_probe,
        "worst_trade_like_events_delta_candidate": worst_trade_like,
        "candidates": rows,
    }


def _activity_inversion_summary(
    candidate_reports: list[dict[str, Any]],
    downstream_activity_regression: dict[str, Any],
) -> dict[str, Any]:
    failed_names = set(
        str(name)
        for name in list(
            downstream_activity_regression.get("signal_sparsity_fix_failed_candidate_names") or []
        )
        if str(name)
    )
    rows: list[dict[str, Any]] = []
    for candidate in candidate_reports:
        name = str(candidate.get("name") or "")
        if name not in failed_names:
            continue
        positive_windows = [
            {
                "input_report": window.get("input_report"),
                "window_days": window.get("window_days"),
                "delta_add_events": window.get("delta_add_events"),
                "delta_trade_like_events": window.get("delta_trade_like_events"),
                "delta_probe_adds": window.get("delta_probe_adds"),
                "activity_non_regression_contract": dict(
                    window.get("activity_non_regression_contract") or {}
                ),
            }
            for window in list(candidate.get("passed_windows") or [])
            if _int(window.get("delta_add_events")) > 0
            and _int(window.get("delta_trade_like_events")) >= 0
            and _int(window.get("delta_probe_adds")) >= 0
        ]
        if not positive_windows:
            continue
        rows.append(
            {
                "candidate_name": name,
                "passed_window_count": candidate.get("passed_window_count"),
                "positive_smoke_activity_windows": positive_windows,
                "downstream_failure": "full_wfo_activity_regression_after_positive_smoke_activity",
            }
        )
    return {
        "available": bool(rows),
        "candidate_count": len(rows),
        "candidate_names": sorted(str(row.get("candidate_name")) for row in rows),
        "diagnostic_label": (
            "short_window_smoke_activity_increase_inverts_to_full_wfo_activity_regression"
            if rows
            else None
        ),
        "candidates": rows,
    }


def _next_candidate_design_contract(
    downstream_activity_regression: dict[str, Any],
    downstream_activity_inversion: dict[str, Any],
) -> dict[str, Any]:
    failed_count = _int(
        downstream_activity_regression.get("signal_sparsity_fix_failed_candidate_count"),
        0,
    )
    inversion_count = _int(downstream_activity_inversion.get("candidate_count"), 0)
    requires_redesign = failed_count > 0 or inversion_count > 0
    return {
        "status": "required_before_next_near_miss_family" if requires_redesign else "monitor",
        "reason": (
            "current_short_window_activity_gains_do_not_survive_full_walk_forward"
            if inversion_count > 0
            else "current_full_walk_forward_candidates_do_not_fix_signal_sparsity"
            if failed_count > 0
            else "no_activity_regression_detected"
        ),
        "blocked_prior_family_candidate_count": failed_count,
        "short_window_activity_inversion_candidate_count": inversion_count,
        "minimum_full_walk_forward_requirements": {
            "probe_add_delta_min": 0,
            "trade_like_events_delta_min": 1,
            "trade_like_activity_increase_required": True,
            "signal_sparsity_fix_requires_trade_like_events_increase": True,
            "compounded_return_delta_min_pct": -5.0,
            "max_drawdown_worsening_max_pct": 3.0,
            "positive_fold_delta_min": 0,
            "activity_inversion_allowed": False,
            "source_replay_lineage_guard_must_pass": True,
        },
        "reject_patterns": [
            "short_window_smoke_activity_increase_inverts_to_full_wfo_activity_regression",
            "full_wfo_probe_add_delta_below_zero",
            "full_wfo_trade_like_events_delta_below_zero",
            "full_wfo_return_degradation_or_drawdown_worsening_used_to_create_signals",
            "mc04_broad_first_touch_relaxation_without_new_365d_evidence",
        ],
        "required_validation_sequence": [
            "smoke_windows_must_pass_activity_non_regression_contract",
            "full_walk_forward_gate_must_run_with_require_nonregressing_activity",
            "promotion_gate_must_show_active_full_walk_forward_candidate_count_above_zero",
            "paper_evidence_only_after_current_fresh_signal_and_operator_review",
        ],
        "runtime_filter_change_allowed": False,
        "paper_or_live_promotion_allowed": False,
        "no_live_order_sent": True,
    }


def build_near_miss_promotion_gate_report(
    smoke_reports: list[tuple[str, dict[str, Any]]],
    *,
    generated_at: datetime | None = None,
    max_return_degradation_pct: float = 5.0,
    max_drawdown_worsening_pct: float = 3.0,
    full_walk_forward_gate_report: dict[str, Any] | None = None,
    full_walk_forward_gate_reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for input_report, report in smoke_reports:
        for row in _candidate_rows(report, input_report=input_report):
            by_candidate.setdefault(str(row.get("name")), []).append(row)
    candidate_reports: list[dict[str, Any]] = []
    for name, rows in sorted(by_candidate.items()):
        failed_windows: list[dict[str, Any]] = []
        passed_windows: list[dict[str, Any]] = []
        safety_blockers_by_window: list[dict[str, Any]] = []
        for row in rows:
            safety_blockers = _safety_blockers(row)
            if safety_blockers:
                safety_blockers_by_window.append(
                    {
                        "input_report": row.get("input_report"),
                        "window_days": row.get("window_days"),
                        "blockers": safety_blockers,
                    }
                )
            passes = (
                row["delta_add_events"] > 0
                and row["delta_return_pct"] >= -abs(float(max_return_degradation_pct))
                and row["delta_max_drawdown_pct"] <= float(max_drawdown_worsening_pct)
                and row["smoke_decision"] == "promote_to_full_walk_forward_evidence_probe_candidate"
                and not safety_blockers
            )
            (passed_windows if passes else failed_windows).append(row)
        candidate_reports.append(
            {
                "name": name,
                "status": "promote_to_full_walk_forward" if rows and not failed_windows else "blocked",
                "window_count": len(rows),
                "passed_window_count": len(passed_windows),
                "failed_window_count": len(failed_windows),
                "safety_blocker_count": len(safety_blockers_by_window),
                "safety_blockers_by_window": safety_blockers_by_window,
                "passed_windows": passed_windows,
                "failed_windows": failed_windows,
            }
        )
    promoted = [item for item in candidate_reports if item["status"] == "promote_to_full_walk_forward"]
    safety_blocker_counts = _count_safety_blockers(candidate_reports)
    primary_safety_blocker = next(iter(safety_blocker_counts), None)
    raw_full_wfo_reports: list[dict[str, Any]] = []
    if full_walk_forward_gate_report:
        raw_full_wfo_reports.append(full_walk_forward_gate_report)
    raw_full_wfo_reports.extend(list(full_walk_forward_gate_reports or []))
    full_wfo_summaries = [_full_walk_forward_gate_summary(report) for report in raw_full_wfo_reports]
    downstream_activity_regression = _activity_regression_rollup(full_wfo_summaries)
    downstream_activity_inversion = _activity_inversion_summary(
        candidate_reports,
        downstream_activity_regression,
    )
    next_candidate_design_contract = _next_candidate_design_contract(
        downstream_activity_regression,
        downstream_activity_inversion,
    )
    full_wfo = full_wfo_summaries[0] if full_wfo_summaries else _full_walk_forward_gate_summary(None)
    paper_candidate_summaries = [
        summary
        for summary in full_wfo_summaries
        if summary.get("status") == "paper_evidence_collection_candidate_available"
    ]
    paper_candidate_names = [
        str(summary.get("candidate_name"))
        for summary in paper_candidate_summaries
        if summary.get("candidate_name")
    ]
    downstream_blocked_names: set[str] = set()
    downstream_blocked_by_name: dict[str, dict[str, Any]] = {}
    downstream_unmapped_blocked_gate = False
    for full_wfo_summary in full_wfo_summaries:
        if full_wfo_summary.get("status") != "blocked_full_walk_forward_gate":
            continue
        full_wfo_candidate_name = str(full_wfo_summary.get("candidate_name") or "").strip()
        if full_wfo_candidate_name:
            downstream_blocked_names.add(full_wfo_candidate_name)
            downstream_blocked_by_name[full_wfo_candidate_name] = full_wfo_summary
        elif len(promoted) == 1:
            promoted_name = str(promoted[0].get("name"))
            downstream_blocked_names.add(promoted_name)
            downstream_blocked_by_name[promoted_name] = full_wfo_summary
        else:
            downstream_unmapped_blocked_gate = True
    for candidate in candidate_reports:
        candidate_name = str(candidate.get("name"))
        if candidate_name in downstream_blocked_names:
            matching_full_wfo = downstream_blocked_by_name.get(candidate_name, full_wfo)
            candidate["downstream_full_walk_forward_status"] = matching_full_wfo.get("status")
            candidate["downstream_full_walk_forward_failed_checks"] = list(
                matching_full_wfo.get("failed_checks") or []
            )
            candidate["final_status"] = "blocked_by_full_walk_forward_gate"
        elif candidate.get("status") == "promote_to_full_walk_forward":
            candidate["final_status"] = "promote_to_full_walk_forward"
    active_promoted = [
        item
        for item in promoted
        if str(item.get("name")) not in downstream_blocked_names
    ]
    activity_failed_names = set(
        str(name)
        for name in list(
            downstream_activity_regression.get("signal_sparsity_fix_failed_candidate_names") or []
        )
        if str(name)
    )
    activity_failed_count = _int(
        downstream_activity_regression.get("signal_sparsity_fix_failed_candidate_count"),
        0,
    )
    downstream_activity_regression_blocks_signal_fix = bool(downstream_blocked_names) and (
        set(downstream_blocked_names) <= activity_failed_names
        or activity_failed_count >= len(downstream_blocked_names)
    )
    full_wfo_paper_candidate = bool(paper_candidate_summaries) and not downstream_unmapped_blocked_gate
    full_wfo_blocked = (
        bool(promoted)
        and not active_promoted
        and bool(downstream_blocked_names)
        and not full_wfo_paper_candidate
    )
    if full_wfo_paper_candidate:
        resolution_status = "full_walk_forward_candidate_passed_paper_evidence_collection_only"
        safe_next_step = "collect_paper_evidence_only_after_fresh_signal_and_operator_review"
        overall_status = "candidate_promoted"
    elif full_wfo_blocked:
        resolution_status = "blocked_by_full_walk_forward_gate"
        safe_next_step = (
            "abandon_current_activity_regressing_near_miss_family_design_non_regressing_signal_candidate"
            if downstream_activity_regression_blocks_signal_fix
            else "inspect_failed_full_walk_forward_gate_before_any_new_near_miss_recipe"
        )
        overall_status = "full_walk_forward_candidate_blocked"
    elif downstream_unmapped_blocked_gate:
        resolution_status = "full_walk_forward_candidate_available_with_unmapped_downstream_gate"
        safe_next_step = "map_full_walk_forward_gate_to_candidate_name_before_paper_evidence"
        overall_status = "candidate_promoted"
    elif active_promoted:
        resolution_status = "full_walk_forward_candidate_available"
        safe_next_step = "promote_candidate_to_full_walk_forward_validation_only"
        overall_status = "candidate_promoted"
    elif safety_blocker_counts:
        resolution_status = "blocked_by_near_miss_safety_contract"
        safe_next_step = "rerun_near_miss_smoke_with_mc12_only_quality_gated_contract"
        overall_status = "no_candidate_promoted"
    else:
        resolution_status = "blocked_by_window_performance_or_smoke_decision"
        safe_next_step = "inspect_failed_windows_before_any_new_near_miss_recipe"
        overall_status = "no_candidate_promoted"
    resolution_plan = {
        "status": resolution_status,
        "primary_safety_blocker": primary_safety_blocker,
        "safety_blocker_counts": safety_blocker_counts,
        "safe_next_step": safe_next_step,
        "full_walk_forward_validation_allowed": bool(active_promoted),
        "paper_evidence_collection_allowed": full_wfo_paper_candidate,
        "paper_evidence_candidate_count": len(paper_candidate_summaries),
        "paper_evidence_candidate_names": paper_candidate_names,
        "runtime_filter_change_allowed": False,
        "paper_or_live_promotion_allowed": False,
        "downstream_full_walk_forward_status": full_wfo.get("status"),
        "downstream_blocked_candidate_names": sorted(downstream_blocked_names),
        "downstream_activity_regression_summary": downstream_activity_regression,
        "downstream_activity_inversion_summary": downstream_activity_inversion,
        "next_candidate_design_contract": next_candidate_design_contract,
        "downstream_activity_regression_blocks_signal_fix": downstream_activity_regression_blocks_signal_fix,
        "primary_downstream_failure": (
            "short_window_activity_inversion_and_full_wfo_activity_regression"
            if downstream_activity_inversion.get("available")
            else "activity_regression_blocks_signal_sparsity_fix"
            if downstream_activity_regression_blocks_signal_fix
            else "full_walk_forward_quality_gate_failed"
            if full_wfo_blocked
            else None
        ),
        "downstream_unmapped_blocked_gate": downstream_unmapped_blocked_gate,
        "unsafe_shortcuts": [
            "allow_mc04_no_clear_first_touch_in_near_miss_probe",
            "allow_missing_allowed_soft_reasons_contract",
            "lower_score_edge_or_reason_stack_floor_without_full_walk_forward",
            "raise_probe_units_above_0_00025",
            "enable_live_orders_from_near_miss_gate",
        ],
        "no_live_order_sent": True,
    }
    return {
        "generated_at": generated_at.isoformat(),
        "overall_status": overall_status,
        "no_live_order_sent": True,
        "gates": {
            "max_return_degradation_pct": float(max_return_degradation_pct),
            "max_drawdown_worsening_pct": float(max_drawdown_worsening_pct),
            "requires_positive_add_event_delta": True,
            "requires_every_input_window_to_pass": True,
            "max_near_miss_probe_units": 0.00025,
            "allowed_soft_reasons": ["MC12_low_confluence"],
            "requires_min_score_at_least": 4,
            "requires_min_score_edge_at_least": 2,
            "requires_min_reason_stack_at_least": 2,
            "requires_max_extension_atr_at_most": 1.5,
            "blocks_mc04_broad_first_touch": True,
        },
        "input_report_count": len(smoke_reports),
        "candidate_count": len(candidate_reports),
        "promoted_candidate_count": len(promoted),
        "active_full_walk_forward_candidate_count": len(active_promoted),
        "active_full_walk_forward_candidate_names": [str(item.get("name")) for item in active_promoted],
        "paper_evidence_candidate_count": len(paper_candidate_summaries),
        "paper_evidence_candidate_names": paper_candidate_names,
        "downstream_blocked_candidate_names": sorted(downstream_blocked_names),
        "safety_blocker_counts": safety_blocker_counts,
        "downstream_activity_regression_summary": downstream_activity_regression,
        "downstream_activity_inversion_summary": downstream_activity_inversion,
        "next_candidate_design_contract": next_candidate_design_contract,
        "downstream_full_walk_forward_gate": full_wfo,
        "downstream_full_walk_forward_gates": full_wfo_summaries,
        "resolution_plan": resolution_plan,
        "candidates": candidate_reports,
        "non_negotiables": [
            "do_not_promote_single_window_near_miss_smoke",
            "do_not_use_rejected_evidence_probe_candidates_for_live_or_paper_bridge",
            "full_walk_forward_is_required_after_this_gate",
            "do_not_ignore_failed_downstream_full_walk_forward_gate",
            "do_not_treat_activity_regressing_full_wfo_candidate_as_signal_sparsity_fix",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Near-Miss Promotion Gate",
        "",
        f"- status: `{report.get('overall_status')}`",
        f"- promoted: `{report.get('promoted_candidate_count')}`",
        f"- candidates: `{report.get('candidate_count')}`",
        f"- resolution_status: `{dict(report.get('resolution_plan') or {}).get('status')}`",
        f"- downstream_full_walk_forward_status: "
        f"`{dict(report.get('downstream_full_walk_forward_gate') or {}).get('status')}`",
        f"- primary_safety_blocker: `{dict(report.get('resolution_plan') or {}).get('primary_safety_blocker')}`",
        f"- safety_blocker_counts: `{report.get('safety_blocker_counts')}`",
        f"- downstream_activity_regression_summary: "
        f"`{json.dumps(report.get('downstream_activity_regression_summary') or {}, ensure_ascii=False)}`",
        f"- downstream_activity_inversion_summary: "
        f"`{json.dumps(report.get('downstream_activity_inversion_summary') or {}, ensure_ascii=False)}`",
        f"- next_candidate_design_contract: "
        f"`{json.dumps(report.get('next_candidate_design_contract') or {}, ensure_ascii=False)}`",
        f"- safe_next_step: `{dict(report.get('resolution_plan') or {}).get('safe_next_step')}`",
        "",
    ]
    for item in list(report.get("candidates") or []):
        lines.append(
            f"- `{item.get('name')}` status `{item.get('status')}` "
            f"passed `{item.get('passed_window_count')}/{item.get('window_count')}`"
        )
    lines.append("")
    return "\n".join(lines)


def _split_paths(raw: str) -> list[Path]:
    paths: list[Path] = []
    for item in str(raw or "").split(","):
        text = item.strip()
        if text:
            paths.append(_resolve(text))
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate near-miss smoke candidates across windows.")
    parser.add_argument("--smoke-reports", default=DEFAULT_SMOKE_REPORTS)
    parser.add_argument("--max-return-degradation-pct", type=float, default=5.0)
    parser.add_argument("--max-drawdown-worsening-pct", type=float, default=3.0)
    parser.add_argument("--full-walk-forward-gate-report", default=DEFAULT_FULL_WALK_FORWARD_GATE_REPORT)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_near_miss_promotion_gate")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = _split_paths(args.smoke_reports)
    reports = [(_display_path(path), _load_json(path)) for path in paths]
    full_walk_forward_gate_paths = _split_paths(args.full_walk_forward_gate_report)
    full_walk_forward_gate_reports = [
        _load_json(path)
        for path in full_walk_forward_gate_paths
        if path.exists()
    ]
    report = build_near_miss_promotion_gate_report(
        reports,
        max_return_degradation_pct=float(args.max_return_degradation_pct),
        max_drawdown_worsening_pct=float(args.max_drawdown_worsening_pct),
        full_walk_forward_gate_reports=full_walk_forward_gate_reports,
    )
    if full_walk_forward_gate_paths:
        report["input_full_walk_forward_gate_reports"] = [
            _display_path(path) for path in full_walk_forward_gate_paths
        ]
        report["input_full_walk_forward_gate_report_exists"] = all(
            path.exists() for path in full_walk_forward_gate_paths
        )
        report["input_full_walk_forward_gate_report"] = _display_path(full_walk_forward_gate_paths[0])
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_near_miss_promotion_gate.json"
        md_path = report_dir / "market_state_rotation_v6_near_miss_promotion_gate.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
