#!/usr/bin/env python3
"""Gate a v6 candidate against a baseline full walk-forward report."""

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


DEFAULT_BASELINE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_imp416_f8_f11_buffer_source415/"
    "market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json"
)
DEFAULT_CANDIDATE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_imp473_profitable_low_activity_diag/"
    "market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json"
)
DEFAULT_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_full_walk_forward_gate"


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


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    aggregate = dict(report.get("aggregate") or {})
    return {
        "fold_count": _int(aggregate.get("fold_count"), len(report.get("folds") or [])),
        "compounded_oos_return_pct": _float(aggregate.get("compounded_oos_return_pct")),
        "avg_oos_return_pct": _float(aggregate.get("avg_oos_return_pct")),
        "min_oos_return_pct": _float(aggregate.get("min_oos_return_pct")),
        "positive_fold_count": _int(aggregate.get("positive_fold_count")),
        "max_fold_drawdown_pct": _float(aggregate.get("max_fold_drawdown_pct")),
        "total_trade_like_events": _int(aggregate.get("total_trade_like_events")),
        "avg_trade_like_events": _float(aggregate.get("avg_trade_like_events")),
        "test_add_by_side_counts": dict(aggregate.get("test_add_by_side_counts") or {}),
        "test_add_by_role_counts": dict(aggregate.get("test_add_by_role_counts") or {}),
        "test_flag_counts": dict(aggregate.get("test_flag_counts") or {}),
    }


def _int_dict(mapping: Any) -> dict[str, int]:
    if not isinstance(mapping, dict):
        return {}
    return {str(key): _int(value) for key, value in mapping.items() if _int(value) != 0}


def _pct_delta(candidate: int | float, baseline: int | float) -> float | None:
    baseline_value = _float(baseline)
    if abs(baseline_value) <= 1e-12:
        return None
    return round((_float(candidate) - baseline_value) / abs(baseline_value) * 100.0, 4)


def _fold_key(fold: dict[str, Any], index: int) -> str:
    raw = fold.get("fold")
    if raw is None or raw == "":
        raw = fold.get("chunk_fold")
    if raw is None or raw == "":
        raw = index + 1
    return str(raw)


def _fold_sort_key(value: Any) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _fold_metric_row(fold: dict[str, Any], index: int) -> dict[str, Any]:
    test_result = dict(fold.get("test_result") or {})
    event_diagnostics = dict(test_result.get("event_diagnostics") or {})
    add_by_role = _int_dict(event_diagnostics.get("add_by_role"))
    add_by_side = _int_dict(event_diagnostics.get("add_by_side"))
    total_return_pct = _float(test_result.get("total_return_pct"))
    return {
        "fold": _fold_key(fold, index),
        "test_start": fold.get("test_start") or fold.get("test_start_at"),
        "test_end": fold.get("test_end") or fold.get("test_end_at"),
        "selected_model_id": fold.get("selected_model_id"),
        "total_return_pct": round(total_return_pct, 4),
        "positive_return": total_return_pct > 0.0,
        "max_drawdown_pct": round(_float(test_result.get("max_drawdown_pct")), 4),
        "trade_like_events": _int(test_result.get("trade_like_events")),
        "add_by_role": add_by_role,
        "add_by_side": add_by_side,
        "probe_adds": _int(add_by_role.get("probe")),
        "base_adds": _int(add_by_role.get("base")),
        "battle_adds": _int(add_by_role.get("battle")),
        "chase_adds": _int(add_by_role.get("chase")),
    }


def _fold_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for index, fold in enumerate(list(report.get("folds") or [])):
        row = _fold_metric_row(dict(fold or {}), index)
        rows[str(row["fold"])] = row
    return rows


def _fold_digest(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    fields = (
        "fold",
        "test_start",
        "test_end",
        "baseline_return_pct",
        "candidate_return_pct",
        "return_delta_pct",
        "baseline_max_drawdown_pct",
        "candidate_max_drawdown_pct",
        "drawdown_delta_pct",
        "baseline_trade_like_events",
        "candidate_trade_like_events",
        "trade_like_events_delta",
        "baseline_probe_adds",
        "candidate_probe_adds",
        "probe_add_delta",
    )
    return {field: row.get(field) for field in fields}


def _fold_delta_diagnostics(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    *,
    max_drawdown_worsening_pct: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    baseline_rows = _fold_map(baseline_report)
    candidate_rows = _fold_map(candidate_report)
    baseline_ids = set(baseline_rows)
    candidate_ids = set(candidate_rows)
    matched_ids = sorted(baseline_ids & candidate_ids, key=_fold_sort_key)
    rows: list[dict[str, Any]] = []
    for fold_id in matched_ids:
        baseline = baseline_rows[fold_id]
        candidate = candidate_rows[fold_id]
        return_delta = round(
            _float(candidate.get("total_return_pct")) - _float(baseline.get("total_return_pct")),
            4,
        )
        drawdown_delta = round(
            _float(candidate.get("max_drawdown_pct")) - _float(baseline.get("max_drawdown_pct")),
            4,
        )
        event_delta = _int(candidate.get("trade_like_events")) - _int(baseline.get("trade_like_events"))
        positive_fold_lost = bool(baseline.get("positive_return")) and not bool(candidate.get("positive_return"))
        positive_fold_gained = (not bool(baseline.get("positive_return"))) and bool(candidate.get("positive_return"))
        row = {
            "fold": fold_id,
            "test_start": candidate.get("test_start") or baseline.get("test_start"),
            "test_end": candidate.get("test_end") or baseline.get("test_end"),
            "baseline_return_pct": baseline.get("total_return_pct"),
            "candidate_return_pct": candidate.get("total_return_pct"),
            "return_delta_pct": return_delta,
            "return_degraded": return_delta < 0.0,
            "return_improved": return_delta > 0.0,
            "baseline_positive_return": bool(baseline.get("positive_return")),
            "candidate_positive_return": bool(candidate.get("positive_return")),
            "positive_fold_lost": positive_fold_lost,
            "positive_fold_gained": positive_fold_gained,
            "baseline_max_drawdown_pct": baseline.get("max_drawdown_pct"),
            "candidate_max_drawdown_pct": candidate.get("max_drawdown_pct"),
            "drawdown_delta_pct": drawdown_delta,
            "drawdown_worsened": drawdown_delta > 0.0,
            "drawdown_improved": drawdown_delta < 0.0,
            "drawdown_gate_violation": drawdown_delta > float(max_drawdown_worsening_pct),
            "baseline_trade_like_events": baseline.get("trade_like_events"),
            "candidate_trade_like_events": candidate.get("trade_like_events"),
            "trade_like_events_delta": event_delta,
            "baseline_probe_adds": baseline.get("probe_adds"),
            "candidate_probe_adds": candidate.get("probe_adds"),
            "probe_add_delta": _int(candidate.get("probe_adds")) - _int(baseline.get("probe_adds")),
            "baseline_add_by_role": dict(baseline.get("add_by_role") or {}),
            "baseline_add_by_side": dict(baseline.get("add_by_side") or {}),
            "candidate_add_by_role": dict(candidate.get("add_by_role") or {}),
            "candidate_add_by_side": dict(candidate.get("add_by_side") or {}),
        }
        rows.append(row)

    worst_return_row = min(rows, key=lambda row: _float(row.get("return_delta_pct")), default=None)
    worst_drawdown_row = max(rows, key=lambda row: _float(row.get("drawdown_delta_pct")), default=None)
    positive_lost_ids = [row["fold"] for row in rows if row.get("positive_fold_lost")]
    drawdown_worsened_ids = [row["fold"] for row in rows if row.get("drawdown_worsened")]
    drawdown_gate_violation_ids = [row["fold"] for row in rows if row.get("drawdown_gate_violation")]
    return_degraded_ids = [row["fold"] for row in rows if row.get("return_degraded")]
    probe_regression_ids = [row["fold"] for row in rows if _int(row.get("probe_add_delta")) < 0]
    event_regression_ids = [row["fold"] for row in rows if _int(row.get("trade_like_events_delta")) < 0]
    activity_regression_ids = sorted(set(probe_regression_ids) | set(event_regression_ids), key=_fold_sort_key)
    probe_regression_and_return_degraded_ids = [
        row["fold"]
        for row in rows
        if _int(row.get("probe_add_delta")) < 0 and bool(row.get("return_degraded"))
    ]
    total_baseline_probe_adds = sum(_int(row.get("baseline_probe_adds")) for row in rows)
    total_candidate_probe_adds = sum(_int(row.get("candidate_probe_adds")) for row in rows)
    total_probe_add_delta = sum(_int(row.get("probe_add_delta")) for row in rows)
    total_baseline_trade_like_events = sum(_int(row.get("baseline_trade_like_events")) for row in rows)
    total_candidate_trade_like_events = sum(_int(row.get("candidate_trade_like_events")) for row in rows)
    total_trade_like_events_delta = sum(_int(row.get("trade_like_events_delta")) for row in rows)
    failed_fold_ids = sorted(
        set(return_degraded_ids) | set(positive_lost_ids) | set(drawdown_worsened_ids),
        key=_fold_sort_key,
    )
    summary = {
        "baseline_fold_count": len(baseline_rows),
        "candidate_fold_count": len(candidate_rows),
        "matched_fold_count": len(rows),
        "unmatched_baseline_folds": sorted(baseline_ids - candidate_ids, key=_fold_sort_key),
        "unmatched_candidate_folds": sorted(candidate_ids - baseline_ids, key=_fold_sort_key),
        "changed_fold_count": sum(
            1
            for row in rows
            if abs(_float(row.get("return_delta_pct"))) > 1e-9
            or abs(_float(row.get("drawdown_delta_pct"))) > 1e-9
            or _int(row.get("trade_like_events_delta")) != 0
        ),
        "return_degraded_fold_count": len(return_degraded_ids),
        "return_improved_fold_count": sum(1 for row in rows if row.get("return_improved")),
        "return_degraded_fold_ids": return_degraded_ids,
        "positive_fold_lost_count": len(positive_lost_ids),
        "positive_fold_gained_count": sum(1 for row in rows if row.get("positive_fold_gained")),
        "positive_fold_lost_ids": positive_lost_ids,
        "drawdown_worsened_fold_count": len(drawdown_worsened_ids),
        "drawdown_improved_fold_count": sum(1 for row in rows if row.get("drawdown_improved")),
        "drawdown_worsened_fold_ids": drawdown_worsened_ids,
        "drawdown_gate_violation_fold_ids": drawdown_gate_violation_ids,
        "baseline_non_positive_fold_count": sum(1 for row in rows if not row.get("baseline_positive_return")),
        "candidate_non_positive_fold_count": sum(1 for row in rows if not row.get("candidate_positive_return")),
        "candidate_non_positive_fold_ids": [
            row["fold"] for row in rows if not row.get("candidate_positive_return")
        ],
        "total_baseline_trade_like_events": total_baseline_trade_like_events,
        "total_candidate_trade_like_events": total_candidate_trade_like_events,
        "total_trade_like_events_delta": total_trade_like_events_delta,
        "trade_like_events_delta_pct": _pct_delta(
            total_candidate_trade_like_events,
            total_baseline_trade_like_events,
        ),
        "total_baseline_probe_adds": total_baseline_probe_adds,
        "total_candidate_probe_adds": total_candidate_probe_adds,
        "total_probe_add_delta": total_probe_add_delta,
        "probe_add_delta_pct": _pct_delta(total_candidate_probe_adds, total_baseline_probe_adds),
        "probe_add_regression_fold_count": len(probe_regression_ids),
        "probe_add_regression_fold_ids": probe_regression_ids,
        "trade_like_event_regression_fold_count": len(event_regression_ids),
        "trade_like_event_regression_fold_ids": event_regression_ids,
        "activity_regression_fold_count": len(activity_regression_ids),
        "activity_regression_fold_ids": activity_regression_ids,
        "probe_regression_and_return_degraded_fold_ids": probe_regression_and_return_degraded_ids,
        "failed_fold_ids": failed_fold_ids,
        "worst_return_degradation_fold": _fold_digest(worst_return_row),
        "worst_drawdown_worsening_fold": _fold_digest(worst_drawdown_row),
    }
    return summary, rows


def _activity_regression_summary(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    deltas: dict[str, Any],
    fold_delta_summary: dict[str, Any],
) -> dict[str, Any]:
    baseline_roles = _int_dict(baseline.get("test_add_by_role_counts"))
    candidate_roles = _int_dict(candidate.get("test_add_by_role_counts"))
    baseline_probe_adds = _int(baseline_roles.get("probe"), _int(fold_delta_summary.get("total_baseline_probe_adds")))
    candidate_probe_adds = _int(
        candidate_roles.get("probe"),
        _int(fold_delta_summary.get("total_candidate_probe_adds")),
    )
    baseline_trade_like_events = _int(baseline.get("total_trade_like_events"))
    candidate_trade_like_events = _int(candidate.get("total_trade_like_events"))
    probe_add_delta = candidate_probe_adds - baseline_probe_adds
    trade_like_events_delta = _int(deltas.get("total_trade_like_events"))
    probe_activity_regressed = probe_add_delta < 0
    trade_like_activity_regressed = trade_like_events_delta < 0
    activity_did_not_increase = trade_like_events_delta <= 0
    strict_signal_sparsity_fix_failure_reasons: list[str] = []
    if activity_did_not_increase:
        strict_signal_sparsity_fix_failure_reasons.append("trade_like_activity_did_not_increase")
    if probe_activity_regressed:
        strict_signal_sparsity_fix_failure_reasons.append("probe_activity_regressed")
    diagnostic_labels: list[str] = []
    if probe_activity_regressed:
        diagnostic_labels.append("candidate_reduces_probe_activity_instead_of_solving_signal_sparsity")
    if trade_like_activity_regressed:
        diagnostic_labels.append("candidate_reduces_total_trade_like_events")
    elif activity_did_not_increase:
        diagnostic_labels.append("candidate_does_not_increase_total_trade_like_events")
    if (
        probe_activity_regressed
        and trade_like_activity_regressed
        and _int(fold_delta_summary.get("return_degraded_fold_count")) > 0
    ):
        diagnostic_labels.append("activity_regression_coincides_with_oos_return_degradation")
    return {
        "baseline_trade_like_events": baseline_trade_like_events,
        "candidate_trade_like_events": candidate_trade_like_events,
        "trade_like_events_delta": trade_like_events_delta,
        "trade_like_events_delta_pct": _pct_delta(candidate_trade_like_events, baseline_trade_like_events),
        "baseline_probe_adds": baseline_probe_adds,
        "candidate_probe_adds": candidate_probe_adds,
        "probe_add_delta": probe_add_delta,
        "probe_add_delta_pct": _pct_delta(candidate_probe_adds, baseline_probe_adds),
        "baseline_add_by_role_counts": baseline_roles,
        "candidate_add_by_role_counts": candidate_roles,
        "probe_activity_regressed": probe_activity_regressed,
        "probe_activity_not_regressed": not probe_activity_regressed,
        "trade_like_activity_regressed": trade_like_activity_regressed,
        "trade_like_activity_increased": trade_like_events_delta > 0,
        "trade_like_activity_increase_required": True,
        "minimum_trade_like_events_delta_for_signal_sparsity_fix": 1,
        "activity_did_not_increase": activity_did_not_increase,
        "signal_sparsity_fix_failed": activity_did_not_increase or probe_activity_regressed,
        "strict_signal_sparsity_fix_failure_reasons": strict_signal_sparsity_fix_failure_reasons,
        "probe_add_regression_fold_count": fold_delta_summary.get("probe_add_regression_fold_count"),
        "probe_add_regression_fold_ids": list(fold_delta_summary.get("probe_add_regression_fold_ids") or []),
        "trade_like_event_regression_fold_count": fold_delta_summary.get(
            "trade_like_event_regression_fold_count"
        ),
        "trade_like_event_regression_fold_ids": list(
            fold_delta_summary.get("trade_like_event_regression_fold_ids") or []
        ),
        "probe_regression_and_return_degraded_fold_ids": list(
            fold_delta_summary.get("probe_regression_and_return_degraded_fold_ids") or []
        ),
        "diagnostic_labels": diagnostic_labels,
    }


def _failure_details(
    failed_checks: list[str],
    *,
    deltas: dict[str, Any],
    fold_delta_summary: dict[str, Any],
    activity_regression_summary: dict[str, Any],
    max_compounded_return_degradation_pct: float,
    max_drawdown_worsening_pct: float,
    min_positive_fold_delta: int,
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    if "compounded_return_degradation" in failed_checks:
        details["compounded_return_degradation"] = {
            "observed_delta_pct": deltas.get("compounded_oos_return_pct"),
            "allowed_min_delta_pct": -abs(float(max_compounded_return_degradation_pct)),
            "return_degraded_fold_count": fold_delta_summary.get("return_degraded_fold_count"),
            "worst_fold": fold_delta_summary.get("worst_return_degradation_fold"),
        }
    if "drawdown_worsening" in failed_checks:
        details["drawdown_worsening"] = {
            "observed_delta_pct": deltas.get("max_fold_drawdown_pct"),
            "allowed_max_delta_pct": float(max_drawdown_worsening_pct),
            "drawdown_worsened_fold_count": fold_delta_summary.get("drawdown_worsened_fold_count"),
            "drawdown_gate_violation_fold_ids": list(
                fold_delta_summary.get("drawdown_gate_violation_fold_ids") or []
            ),
            "worst_fold": fold_delta_summary.get("worst_drawdown_worsening_fold"),
        }
    if "positive_fold_count_degradation" in failed_checks:
        details["positive_fold_count_degradation"] = {
            "observed_delta": deltas.get("positive_fold_count"),
            "allowed_min_delta": int(min_positive_fold_delta),
            "positive_fold_lost_count": fold_delta_summary.get("positive_fold_lost_count"),
            "positive_fold_lost_ids": list(fold_delta_summary.get("positive_fold_lost_ids") or []),
        }
    if "source_replay_lineage_guard_failed" in failed_checks:
        details["source_replay_lineage_guard_failed"] = {
            "resolution": "rerun_candidate_with_valid_source_replay_lineage_before_any_paper_or_live_use"
        }
    if failed_checks and bool(activity_regression_summary.get("signal_sparsity_fix_failed")):
        details["activity_regression"] = {
            "trade_like_events_delta": activity_regression_summary.get("trade_like_events_delta"),
            "trade_like_events_delta_pct": activity_regression_summary.get("trade_like_events_delta_pct"),
            "probe_add_delta": activity_regression_summary.get("probe_add_delta"),
            "probe_add_delta_pct": activity_regression_summary.get("probe_add_delta_pct"),
            "probe_activity_regressed": activity_regression_summary.get("probe_activity_regressed"),
            "trade_like_activity_regressed": activity_regression_summary.get("trade_like_activity_regressed"),
            "trade_like_activity_increased": activity_regression_summary.get("trade_like_activity_increased"),
            "trade_like_activity_increase_required": activity_regression_summary.get(
                "trade_like_activity_increase_required"
            ),
            "minimum_trade_like_events_delta_for_signal_sparsity_fix": (
                activity_regression_summary.get(
                    "minimum_trade_like_events_delta_for_signal_sparsity_fix"
                )
            ),
            "activity_did_not_increase": activity_regression_summary.get("activity_did_not_increase"),
            "strict_signal_sparsity_fix_failure_reasons": list(
                activity_regression_summary.get("strict_signal_sparsity_fix_failure_reasons")
                or []
            ),
            "diagnostic_labels": list(activity_regression_summary.get("diagnostic_labels") or []),
            "resolution": "do_not_treat_this_candidate_as_a_signal_sparsity_fix_without_a_new_non_regressing_activity_design",
        }
    return details


def _root_cause_hints(
    failed_checks: list[str],
    *,
    deltas: dict[str, Any],
    fold_delta_summary: dict[str, Any],
    activity_regression_summary: dict[str, Any],
) -> list[str]:
    hints: list[str] = []
    matched_count = _int(fold_delta_summary.get("matched_fold_count"))
    return_degraded_count = _int(fold_delta_summary.get("return_degraded_fold_count"))
    if matched_count > 0 and return_degraded_count == matched_count:
        hints.append("candidate_underperforms_baseline_in_every_matched_oos_fold")
    elif return_degraded_count > 0:
        hints.append("candidate_underperforms_baseline_in_multiple_oos_folds")
    if _int(fold_delta_summary.get("positive_fold_lost_count")) > 0:
        hints.append("candidate_turns_previously_positive_oos_folds_negative")
    if _int(fold_delta_summary.get("drawdown_worsened_fold_count")) > 0:
        hints.append("candidate_increases_oos_drawdown_in_multiple_folds")
    if list(fold_delta_summary.get("drawdown_gate_violation_fold_ids") or []):
        hints.append("drawdown_regression_exceeds_gate_in_specific_folds")
    if _int(fold_delta_summary.get("total_candidate_probe_adds")) > 0 and return_degraded_count > 0:
        hints.append("probe_activity_present_but_does_not_clear_full_walk_forward_quality_bar")
    if abs(_int(fold_delta_summary.get("total_trade_like_events_delta"))) <= 5 and failed_checks:
        hints.append("activity_delta_too_small_to_offset_return_or_drawdown_regression")
    if _float(deltas.get("compounded_oos_return_pct")) < 0.0 and "compounded_return_degradation" in failed_checks:
        hints.append("aggregate_compounded_oos_return_regression_blocks_signal_candidate")
    for label in activity_regression_summary.get("diagnostic_labels") or []:
        if str(label) not in hints:
            hints.append(str(label))
    return hints


def _is_neutral_equivalent(deltas: dict[str, Any]) -> bool:
    float_fields = (
        "compounded_oos_return_pct",
        "avg_oos_return_pct",
        "min_oos_return_pct",
        "max_fold_drawdown_pct",
        "avg_trade_like_events",
    )
    int_fields = ("positive_fold_count", "total_trade_like_events")
    return all(abs(_float(deltas.get(field))) <= 1e-9 for field in float_fields) and all(
        _int(deltas.get(field)) == 0 for field in int_fields
    )


def _promotion_type(*, failed_checks: list[str], deltas: dict[str, Any]) -> str:
    if failed_checks:
        return "blocked"
    if _is_neutral_equivalent(deltas):
        return "neutral_equivalent"
    if _float(deltas.get("compounded_oos_return_pct")) > 0.0:
        return "return_improving"
    if _float(deltas.get("max_fold_drawdown_pct")) < 0.0:
        return "risk_reducing_tradeoff"
    if _int(deltas.get("total_trade_like_events")) > 0:
        return "activity_tradeoff"
    return "non_degrading_tradeoff"


def build_full_walk_forward_gate_report(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    *,
    generated_at: datetime | None = None,
    candidate_name: str | None = None,
    max_compounded_return_degradation_pct: float = 5.0,
    max_drawdown_worsening_pct: float = 3.0,
    min_positive_fold_delta: int = 0,
    require_nonregressing_activity: bool = False,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    baseline = _summary(baseline_report)
    candidate = _summary(candidate_report)
    fold_delta_summary, fold_deltas = _fold_delta_diagnostics(
        baseline_report,
        candidate_report,
        max_drawdown_worsening_pct=max_drawdown_worsening_pct,
    )
    deltas = {
        "compounded_oos_return_pct": round(
            candidate["compounded_oos_return_pct"] - baseline["compounded_oos_return_pct"],
            4,
        ),
        "avg_oos_return_pct": round(candidate["avg_oos_return_pct"] - baseline["avg_oos_return_pct"], 4),
        "min_oos_return_pct": round(candidate["min_oos_return_pct"] - baseline["min_oos_return_pct"], 4),
        "positive_fold_count": candidate["positive_fold_count"] - baseline["positive_fold_count"],
        "max_fold_drawdown_pct": round(
            candidate["max_fold_drawdown_pct"] - baseline["max_fold_drawdown_pct"],
            4,
        ),
        "total_trade_like_events": candidate["total_trade_like_events"] - baseline["total_trade_like_events"],
        "avg_trade_like_events": round(candidate["avg_trade_like_events"] - baseline["avg_trade_like_events"], 4),
    }
    activity_regression_summary = _activity_regression_summary(
        baseline,
        candidate,
        deltas=deltas,
        fold_delta_summary=fold_delta_summary,
    )
    failed_checks: list[str] = []
    if deltas["compounded_oos_return_pct"] < -abs(float(max_compounded_return_degradation_pct)):
        failed_checks.append("compounded_return_degradation")
    if deltas["max_fold_drawdown_pct"] > float(max_drawdown_worsening_pct):
        failed_checks.append("drawdown_worsening")
    if deltas["positive_fold_count"] < int(min_positive_fold_delta):
        failed_checks.append("positive_fold_count_degradation")
    lineage_guard = dict(candidate_report.get("source_replay_lineage_guard") or {})
    if bool(lineage_guard.get("failed")):
        failed_checks.append("source_replay_lineage_guard_failed")
    if bool(require_nonregressing_activity) and bool(
        activity_regression_summary.get("signal_sparsity_fix_failed")
    ):
        failed_checks.append("activity_regression_blocks_signal_sparsity_fix")
    promotion_type = _promotion_type(failed_checks=failed_checks, deltas=deltas)
    overall_status = "blocked" if failed_checks else promotion_type
    decision = (
        "do_not_promote_to_paper_or_live"
        if failed_checks
        else "do_not_replace_current_candidate_without_non_metric_reason"
        if promotion_type == "neutral_equivalent"
        else "eligible_for_paper_evidence_collection_only"
    )
    failure_details = _failure_details(
        failed_checks,
        deltas=deltas,
        fold_delta_summary=fold_delta_summary,
        activity_regression_summary=activity_regression_summary,
        max_compounded_return_degradation_pct=max_compounded_return_degradation_pct,
        max_drawdown_worsening_pct=max_drawdown_worsening_pct,
        min_positive_fold_delta=min_positive_fold_delta,
    )
    return {
        "generated_at": generated_at.isoformat(),
        "candidate_name": candidate_name,
        "overall_status": overall_status,
        "no_live_order_sent": True,
        "gates": {
            "max_compounded_return_degradation_pct": float(max_compounded_return_degradation_pct),
            "max_drawdown_worsening_pct": float(max_drawdown_worsening_pct),
            "min_positive_fold_delta": int(min_positive_fold_delta),
            "lineage_guard_must_not_fail": True,
            "require_nonregressing_activity": bool(require_nonregressing_activity),
        },
        "failed_checks": failed_checks,
        "baseline": baseline,
        "candidate": candidate,
        "deltas": deltas,
        "activity_regression_summary": activity_regression_summary,
        "fold_delta_summary": fold_delta_summary,
        "fold_deltas": fold_deltas,
        "failure_details": failure_details,
        "root_cause_hints": _root_cause_hints(
            failed_checks,
            deltas=deltas,
            fold_delta_summary=fold_delta_summary,
            activity_regression_summary=activity_regression_summary,
        ),
        "promotion_type": promotion_type,
        "candidate_lineage_guard": lineage_guard,
        "decision": decision,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Full Walk-Forward Gate",
        "",
        f"- status: `{report.get('overall_status')}`",
        f"- promotion_type: `{report.get('promotion_type')}`",
        f"- decision: `{report.get('decision')}`",
        f"- failed_checks: `{json.dumps(report.get('failed_checks') or [], ensure_ascii=False)}`",
        f"- deltas: `{json.dumps(report.get('deltas') or {}, ensure_ascii=False)}`",
        f"- activity_regression_summary: `{json.dumps(report.get('activity_regression_summary') or {}, ensure_ascii=False)}`",
        f"- fold_delta_summary: `{json.dumps(report.get('fold_delta_summary') or {}, ensure_ascii=False)}`",
        f"- root_cause_hints: `{json.dumps(report.get('root_cause_hints') or [], ensure_ascii=False)}`",
        "",
    ]
    failure_details = dict(report.get("failure_details") or {})
    if failure_details:
        lines.extend(
            [
                "## Failure Details",
                "",
                f"`{json.dumps(failure_details, ensure_ascii=False)}`",
                "",
            ]
        )
    worst_folds = [
        dict(report.get("fold_delta_summary") or {}).get("worst_return_degradation_fold"),
        dict(report.get("fold_delta_summary") or {}).get("worst_drawdown_worsening_fold"),
    ]
    worst_folds = [fold for fold in worst_folds if fold]
    if worst_folds:
        lines.extend(
            [
                "## Worst Folds",
                "",
                f"`{json.dumps(worst_folds, ensure_ascii=False)}`",
                "",
            ]
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate v6 full walk-forward candidate against baseline.")
    parser.add_argument("--baseline-report", default=DEFAULT_BASELINE_REPORT)
    parser.add_argument("--candidate-report", default=DEFAULT_CANDIDATE_REPORT)
    parser.add_argument("--candidate-name", default="")
    parser.add_argument("--max-compounded-return-degradation-pct", type=float, default=5.0)
    parser.add_argument("--max-drawdown-worsening-pct", type=float, default=3.0)
    parser.add_argument("--min-positive-fold-delta", type=int, default=0)
    parser.add_argument(
        "--require-nonregressing-activity",
        action="store_true",
        help=(
            "Block signal-sparsity-fix candidates when full walk-forward probe or "
            "trade-like activity regresses versus baseline."
        ),
    )
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline_path = _resolve(args.baseline_report)
    candidate_path = _resolve(args.candidate_report)
    report = build_full_walk_forward_gate_report(
        _load_json(baseline_path),
        _load_json(candidate_path),
        candidate_name=args.candidate_name or None,
        max_compounded_return_degradation_pct=float(args.max_compounded_return_degradation_pct),
        max_drawdown_worsening_pct=float(args.max_drawdown_worsening_pct),
        min_positive_fold_delta=int(args.min_positive_fold_delta),
        require_nonregressing_activity=bool(args.require_nonregressing_activity),
    )
    report["input_baseline_report"] = _display_path(baseline_path)
    report["input_candidate_report"] = _display_path(candidate_path)
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_full_walk_forward_gate.json"
        md_path = report_dir / "market_state_rotation_v6_full_walk_forward_gate.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
