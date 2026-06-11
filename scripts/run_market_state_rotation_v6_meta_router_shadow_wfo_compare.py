#!/usr/bin/env python3
"""Compare v6 adaptive meta-router shadow WFO reports against the baseline.

This is a research-only promotion gate. It evaluates common folds only, so a
single-fold smoke run is compared against the same baseline fold instead of the
full historical baseline. It never submits live orders.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]

DEFAULT_SOURCE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_imp490_current_top_candidate_audit/"
    "market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json"
)
DEFAULT_SHADOW_WFO_ROOT = "reports/validation/diagnostics/market_state_rotation_v6_meta_router_shadow_wfo"
DEFAULT_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_meta_router_shadow_wfo_compare"
CANONICAL_RECIPE_IDS = {
    "winner_refill_after_trim_100_r010_s4",
    "winner_refill_after_trim_100_r010_s4_formal",
}
EXPERIMENTAL_RECIPE_MARKERS = (
    "profit_unlock",
    "cost180",
    "scratch",
    "debug",
    "check",
    "probe",
)
CONDITIONAL_WINNER_REFILL_OVERLAY_KEYS = (
    "winner_pyramid_min_extension_after_selection",
)


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = _resolve(path)
    if resolved is None:
        raise ValueError("path is required")
    return dict(json.loads(resolved.read_text(encoding="utf-8")))


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


def _fold_number(fold: dict[str, Any]) -> int | None:
    value = fold.get("fold")
    if value is None:
        value = fold.get("chunk_fold")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _folds_by_number(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for fold in list(report.get("folds") or []):
        number = _fold_number(dict(fold))
        if number is not None:
            rows[number] = dict(fold)
    return rows


def _compound(returns_pct: list[float]) -> float:
    equity = 1.0
    for ret in returns_pct:
        equity *= max(1.0 + ret / 100.0, 1e-12)
    return (equity - 1.0) * 100.0


def _merge_counts(target: dict[str, int], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for key, value in source.items():
        target[str(key)] = target.get(str(key), 0) + int(value or 0)


def _role_share(counts: dict[str, int]) -> dict[str, float]:
    total = max(sum(int(value) for value in counts.values()), 1)
    return {key: round(int(value) / total, 6) for key, value in sorted(counts.items())}


def _mode_summary(folds: list[dict[str, Any]]) -> dict[str, Any]:
    modes: dict[str, dict[str, Any]] = {}
    add_counts: dict[str, int] = {}
    remove_counts: dict[str, int] = {}
    for fold in folds:
        result = dict(fold.get("test_result") or {})
        diagnostics = dict(result.get("event_diagnostics") or {})
        _merge_counts(add_counts, diagnostics.get("add_by_router_mode"))
        _merge_counts(remove_counts, diagnostics.get("remove_by_router_mode"))
        for mode, payload_raw in dict(result.get("router_mode_performance") or {}).items():
            payload = dict(payload_raw or {})
            row = modes.setdefault(
                str(mode),
                {
                    "returns": [],
                    "bars": 0,
                    "exposed_bars": 0,
                    "add_events": 0,
                    "remove_events": 0,
                    "max_drawdown_pct": 0.0,
                },
            )
            row["returns"].append(_float(payload.get("return_pct")))
            row["bars"] = int(row["bars"]) + int(payload.get("bars") or 0)
            row["exposed_bars"] = int(row["exposed_bars"]) + int(payload.get("exposed_bars") or 0)
            row["add_events"] = int(row["add_events"]) + int(payload.get("add_events") or 0)
            row["remove_events"] = int(row["remove_events"]) + int(payload.get("remove_events") or 0)
            row["max_drawdown_pct"] = max(
                _float(row["max_drawdown_pct"]),
                _float(payload.get("max_drawdown_pct")),
            )

    compact: dict[str, Any] = {}
    for mode, row in sorted(modes.items()):
        returns = list(row.get("returns") or [])
        bars = max(int(row.get("bars") or 0), 1)
        compact[mode] = {
            "fold_count": len(returns),
            "positive_fold_count": sum(1 for item in returns if item > 0.0),
            "compounded_return_pct": _pct(_compound(returns)),
            "min_return_pct": _pct(min(returns) if returns else 0.0),
            "max_drawdown_pct": _pct(row.get("max_drawdown_pct")),
            "bars": int(row.get("bars") or 0),
            "exposed_bars": int(row.get("exposed_bars") or 0),
            "exposure_share": round(int(row.get("exposed_bars") or 0) / bars, 6),
            "add_events": int(row.get("add_events") or 0),
            "remove_events": int(row.get("remove_events") or 0),
        }
    return {
        "active_modes": [mode for mode, row in compact.items() if int(row.get("bars") or 0) > 0],
        "modes": compact,
        "add_by_router_mode": dict(sorted(add_counts.items())),
        "remove_by_router_mode": dict(sorted(remove_counts.items())),
    }


def _metrics_for_folds(report: dict[str, Any], fold_numbers: list[int]) -> dict[str, Any]:
    by_number = _folds_by_number(report)
    folds = [by_number[number] for number in fold_numbers if number in by_number]
    returns: list[float] = []
    drawdowns: list[float] = []
    costs: list[float] = []
    trade_events = 0
    add_by_role: dict[str, int] = {}
    health_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    for fold in folds:
        result = dict(fold.get("test_result") or {})
        returns.append(_float(result.get("total_return_pct")))
        drawdowns.append(_float(result.get("max_drawdown_pct")))
        costs.append(_float(result.get("estimated_cost_drag_pct")))
        trade_events += int(result.get("trade_like_events") or 0)
        diagnostics = dict(result.get("event_diagnostics") or {})
        _merge_counts(add_by_role, diagnostics.get("add_by_role"))
        health = str(diagnostics.get("health") or "unknown")
        health_counts[health] = health_counts.get(health, 0) + 1
        for flag in list(diagnostics.get("flags") or []):
            flag_counts[str(flag)] = flag_counts.get(str(flag), 0) + 1

    return {
        "fold_count": len(folds),
        "folds": fold_numbers,
        "compounded_return_pct": _pct(_compound(returns)),
        "avg_return_pct": _pct(sum(returns) / len(returns) if returns else 0.0),
        "min_return_pct": _pct(min(returns) if returns else 0.0),
        "positive_fold_count": sum(1 for item in returns if item > 0.0),
        "max_drawdown_pct": _pct(max(drawdowns) if drawdowns else 0.0),
        "avg_cost_drag_pct": _pct(sum(costs) / len(costs) if costs else 0.0),
        "max_cost_drag_pct": _pct(max(costs) if costs else 0.0),
        "trade_like_events": trade_events,
        "add_by_role": dict(sorted(add_by_role.items())),
        "add_role_share": _role_share(add_by_role),
        "health_counts": dict(sorted(health_counts.items())),
        "flag_counts": dict(sorted(flag_counts.items())),
        "router_mode_summary": _mode_summary(folds),
    }


def _candidate_report_paths(shadow_wfo_root: str | Path) -> list[Path]:
    root = _resolve(shadow_wfo_root)
    if root is None or not root.exists():
        return []
    return sorted(root.glob("*/market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json"))


def _lineage_status(report: dict[str, Any]) -> dict[str, Any]:
    guard = dict(report.get("source_replay_lineage_guard") or {})
    diagnostics = dict(report.get("source_replay_diagnostics") or {})
    unresolved_material = int(
        guard.get("unresolved_material_metric_mismatch_count")
        or diagnostics.get("unresolved_material_metric_mismatch_count")
        or 0
    )
    unresolved_model = int(
        guard.get("selected_model_unresolved_mismatch_count")
        or diagnostics.get("selected_model_unresolved_mismatch_count")
        or 0
    )
    return {
        "guard_status": guard.get("status") or ("failed" if guard.get("failed") else "unknown"),
        "failed": bool(guard.get("failed")),
        "message": guard.get("message"),
        "unresolved_material_drift_count": unresolved_material,
        "selected_model_unresolved_mismatch_count": unresolved_model,
        "unresolved_material_folds": list(guard.get("unresolved_material_folds") or []),
    }


def _lineage_policy(recipe_id: Any) -> str:
    recipe = str(recipe_id or "")
    if recipe.startswith("router_contract_observe_only"):
        return "must_match_source"
    return "explicit_new_candidate"


def _fold_result_summary(fold: dict[str, Any] | None) -> dict[str, Any]:
    row = dict(fold or {})
    result = dict(row.get("test_result") or {})
    diagnostics = dict(result.get("event_diagnostics") or {})
    return {
        "selected_model_id": row.get("selected_model_id") or result.get("model_id"),
        "return_pct": _pct(result.get("total_return_pct")),
        "max_drawdown_pct": _pct(result.get("max_drawdown_pct")),
        "cost_drag_pct": _pct(result.get("estimated_cost_drag_pct")),
        "trade_like_events": int(result.get("trade_like_events") or 0),
        "health": diagnostics.get("health"),
        "flags": list(diagnostics.get("flags") or []),
        "add_by_side": dict(diagnostics.get("add_by_side") or {}),
        "add_by_role": dict(diagnostics.get("add_by_role") or {}),
    }


def _model_delta_tokens(candidate_model_id: Any, baseline_model_id: Any) -> dict[str, list[str]]:
    candidate_tokens = [token for token in str(candidate_model_id or "").split(":") if token]
    baseline_tokens = [token for token in str(baseline_model_id or "").split(":") if token]
    baseline_set = set(baseline_tokens)
    candidate_set = set(candidate_tokens)
    return {
        "candidate_only": [token for token in candidate_tokens if token not in baseline_set],
        "baseline_only": [token for token in baseline_tokens if token not in candidate_set],
    }


def _lineage_review_packet(
    *,
    lineage: dict[str, Any],
    baseline_by_fold: dict[int, dict[str, Any]],
    candidate_by_fold: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    unresolved_folds = [
        int(fold)
        for fold in list(lineage.get("unresolved_material_folds") or [])
        if isinstance(fold, int) or str(fold).isdigit()
    ]
    rows: list[dict[str, Any]] = []
    for fold in unresolved_folds:
        baseline = _fold_result_summary(baseline_by_fold.get(fold))
        candidate = _fold_result_summary(candidate_by_fold.get(fold))
        token_delta = _model_delta_tokens(
            candidate.get("selected_model_id"),
            baseline.get("selected_model_id"),
        )
        same_trade_count = (
            int(candidate.get("trade_like_events") or 0)
            == int(baseline.get("trade_like_events") or 0)
        )
        same_add_distribution = (
            dict(candidate.get("add_by_side") or {}) == dict(baseline.get("add_by_side") or {})
            and dict(candidate.get("add_by_role") or {}) == dict(baseline.get("add_by_role") or {})
        )
        size_overlay_tokens = [
            token
            for token in list(token_delta.get("candidate_only") or [])
            if token.startswith("wfRtSel")
        ]
        winner_refill_tokens = [
            token
            for token in list(token_delta.get("candidate_only") or [])
            if token.startswith("wfWinPyr")
        ]
        baseline_add_by_role = dict(baseline.get("add_by_role") or {})
        candidate_add_by_role = dict(candidate.get("add_by_role") or {})
        baseline_chase_adds = int(baseline_add_by_role.get("chase") or 0)
        candidate_chase_adds = int(candidate_add_by_role.get("chase") or 0)
        intentional_winner_refill_delta = (
            bool(winner_refill_tokens)
            and int(candidate.get("trade_like_events") or 0)
            >= int(baseline.get("trade_like_events") or 0)
            and candidate_chase_adds >= baseline_chase_adds
        )
        if size_overlay_tokens and same_trade_count and same_add_distribution:
            interpretation = "intentional_size_overlay_delta_detected"
        elif intentional_winner_refill_delta:
            interpretation = "intentional_winner_refill_delta_detected"
        else:
            interpretation = "operator_review_required_unclassified_lineage_delta"
        rows.append(
            {
                "fold": fold,
                "baseline": baseline,
                "candidate": candidate,
                "delta": {
                    "return_pct": _pct(
                        _float(candidate.get("return_pct")) - _float(baseline.get("return_pct"))
                    ),
                    "max_drawdown_pct": _pct(
                        _float(candidate.get("max_drawdown_pct"))
                        - _float(baseline.get("max_drawdown_pct"))
                    ),
                    "cost_drag_pct": _pct(
                        _float(candidate.get("cost_drag_pct"))
                        - _float(baseline.get("cost_drag_pct"))
                    ),
                    "trade_like_events": int(candidate.get("trade_like_events") or 0)
                    - int(baseline.get("trade_like_events") or 0),
                },
                "model_token_delta": token_delta,
                "size_overlay_tokens": size_overlay_tokens,
                "winner_refill_tokens": winner_refill_tokens,
                "same_trade_count": same_trade_count,
                "same_add_distribution": same_add_distribution,
                "interpretation": interpretation,
            }
        )

    review_required = bool(lineage.get("guard_status") and lineage.get("guard_status") != "pass") or bool(rows)
    interpretations = {str(row.get("interpretation") or "") for row in rows}
    intentional_interpretations = {
        "intentional_size_overlay_delta_detected",
        "intentional_winner_refill_delta_detected",
    }
    if rows and interpretations == {"intentional_size_overlay_delta_detected"}:
        summary = "lineage_watch_is_limited_to_intentional_size_overlay_folds"
    elif rows and interpretations <= intentional_interpretations:
        summary = "lineage_watch_is_limited_to_intentional_execution_overlay_folds"
    elif review_required:
        summary = "lineage_review_required_for_unclassified_candidate_delta"
    else:
        summary = "no_lineage_review_required"
    return {
        "required": review_required,
        "status": "pending_operator_lineage_review" if review_required else "not_required",
        "unresolved_material_folds": unresolved_folds,
        "fold_count": len(rows),
        "folds": rows,
        "summary": summary,
        "no_live_order_sent": True,
    }


def _execution_change_audit(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    *,
    max_return_giveback_pct: float,
    max_risk_adjusted_return_giveback_fraction: float,
    min_risk_adjusted_drawdown_reduction_fraction: float,
    max_drawdown_increase_pct: float,
    max_cost_increase_pct: float,
) -> dict[str, Any]:
    return_delta = _float(candidate.get("return_delta_vs_baseline_pct"))
    drawdown_delta = _float(candidate.get("drawdown_delta_vs_baseline_pct"))
    cost_delta = _float(candidate.get("cost_delta_vs_baseline_pct"))
    trade_event_delta = int(candidate.get("trade_event_delta_vs_baseline") or 0)
    baseline_return_pct = _float(baseline.get("compounded_return_pct"))
    baseline_drawdown_pct = _float(baseline.get("max_drawdown_pct"))
    baseline_terminal_pct = max(1e-9, 100.0 + baseline_return_pct)
    return_giveback_fraction = max(0.0, -return_delta) / baseline_terminal_pct
    drawdown_reduction_fraction = (
        max(0.0, -drawdown_delta) / max(1e-9, baseline_drawdown_pct)
    )
    metric_delta_detected = any(
        [
            _nonzero_delta(return_delta),
            _nonzero_delta(drawdown_delta),
            _nonzero_delta(cost_delta),
        ]
    )
    execution_delta_detected = metric_delta_detected or trade_event_delta != 0
    return_upgrade_ready = (
        return_delta > 0.0
        and drawdown_delta <= abs(float(max_drawdown_increase_pct))
        and cost_delta <= abs(float(max_cost_increase_pct))
    )
    risk_compression_detected = (
        drawdown_delta < 0.0 and cost_delta <= abs(float(max_cost_increase_pct))
    )
    risk_compression_ready = (
        risk_compression_detected and return_delta >= -abs(float(max_return_giveback_pct))
    )
    risk_adjusted_compression_ready = (
        risk_compression_detected
        and return_giveback_fraction
        <= max(0.0, float(max_risk_adjusted_return_giveback_fraction))
        and drawdown_reduction_fraction
        >= max(0.0, float(min_risk_adjusted_drawdown_reduction_fraction))
        and cost_delta <= 0.0
    )
    beneficial_metric_delta_detected = (
        return_upgrade_ready or risk_compression_ready or risk_adjusted_compression_ready
    )
    strict_non_worse_metric_profile = (
        (return_delta > 0.0 or drawdown_delta < 0.0 or cost_delta < 0.0)
        and return_delta >= 0.0
        and drawdown_delta <= 0.0
        and cost_delta <= 0.0
    )
    mode_summary = dict(candidate.get("router_mode_summary") or {})
    active_modes = list(mode_summary.get("active_modes") or [])
    blockers: list[str] = []
    notes: list[str] = []
    if not execution_delta_detected:
        blockers.append("candidate_does_not_change_return_drawdown_cost_or_trade_events")
        if active_modes:
            notes.append("router_modes_are_descriptive_only_for_this_candidate")
    if execution_delta_detected and not beneficial_metric_delta_detected:
        notes.append("execution_changed_without_non_worse_return_drawdown_and_cost_profile")
    if return_delta > 0.0 and drawdown_delta > abs(float(max_drawdown_increase_pct)):
        blockers.append("return_upgrade_drawdown_increase_exceeds_gate")
    if return_delta > 0.0 and cost_delta > abs(float(max_cost_increase_pct)):
        blockers.append("return_upgrade_cost_increase_exceeds_gate")
    if risk_compression_detected and not risk_compression_ready:
        blockers.append("risk_compression_return_giveback_exceeds_gate")
    if drawdown_delta < 0.0 and cost_delta > abs(float(max_cost_increase_pct)):
        blockers.append("risk_compression_cost_increase_exceeds_gate")

    if return_upgrade_ready:
        status = "performance_metric_delta_detected"
    elif risk_compression_ready:
        status = "risk_compression_metric_delta_detected"
    elif risk_adjusted_compression_ready:
        status = "risk_adjusted_compression_metric_delta_detected"
    elif risk_compression_detected:
        status = "risk_compression_return_giveback_exceeds_gate"
    elif execution_delta_detected:
        status = "execution_delta_without_metric_improvement"
    else:
        status = "decomposition_only_no_execution_delta"
    return {
        "status": status,
        "execution_delta_detected": execution_delta_detected,
        "metric_delta_detected": metric_delta_detected,
        "beneficial_metric_delta_detected": beneficial_metric_delta_detected,
        "strict_non_worse_metric_profile": strict_non_worse_metric_profile,
        "performance_upgrade_ready": return_upgrade_ready,
        "risk_compression_detected": risk_compression_detected,
        "risk_compression_ready": risk_compression_ready,
        "risk_adjusted_compression_ready": risk_adjusted_compression_ready,
        "return_delta_vs_baseline_pct": _pct(return_delta),
        "return_giveback_fraction_vs_baseline": _pct(return_giveback_fraction),
        "drawdown_delta_vs_baseline_pct": _pct(drawdown_delta),
        "drawdown_reduction_fraction_vs_baseline": _pct(drawdown_reduction_fraction),
        "cost_delta_vs_baseline_pct": _pct(cost_delta),
        "trade_event_delta_vs_baseline": trade_event_delta,
        "candidate_trade_like_events": int(candidate.get("trade_like_events") or 0),
        "baseline_trade_like_events": int(baseline.get("trade_like_events") or 0),
        "active_router_modes": active_modes,
        "blockers": blockers,
        "notes": notes,
    }


def _overfit_audit(
    report: dict[str, Any],
    *,
    baseline_by_fold: dict[int, dict[str, Any]],
    candidate_by_fold: dict[int, dict[str, Any]],
    common_folds: list[int],
) -> dict[str, Any]:
    config_overrides = dict(report.get("config_overrides") or {})
    conditional_keys = [
        key
        for key in CONDITIONAL_WINNER_REFILL_OVERLAY_KEYS
        if config_overrides.get(key) is True
    ]
    model_token_folds: list[int] = []
    fold_rows: list[dict[str, Any]] = []
    positive_deltas: list[tuple[int, float]] = []
    changed_folds: list[int] = []
    for fold in common_folds:
        baseline_result = dict(dict(baseline_by_fold.get(fold) or {}).get("test_result") or {})
        candidate_row = dict(candidate_by_fold.get(fold) or {})
        candidate_result = dict(candidate_row.get("test_result") or {})
        model_id = str(candidate_result.get("model_id") or candidate_row.get("selected_model_id") or "")
        if "wfWinPyrMinExtAS" in model_id:
            model_token_folds.append(int(fold))
        return_delta = _float(candidate_result.get("total_return_pct")) - _float(
            baseline_result.get("total_return_pct")
        )
        event_delta = int(candidate_result.get("trade_like_events") or 0) - int(
            baseline_result.get("trade_like_events") or 0
        )
        if _nonzero_delta(return_delta) or event_delta != 0:
            changed_folds.append(int(fold))
            fold_rows.append(
                {
                    "fold": int(fold),
                    "return_delta_pct": _pct(return_delta),
                    "trade_event_delta": int(event_delta),
                    "conditional_token_applied": "wfWinPyrMinExtAS" in model_id,
                }
            )
        if return_delta > 0.0:
            positive_deltas.append((int(fold), return_delta))
    total_positive_delta = sum(delta for _, delta in positive_deltas)
    top_fold = max(positive_deltas, key=lambda item: item[1], default=None)
    top_share = (
        max(delta for _, delta in positive_deltas) / total_positive_delta
        if total_positive_delta > 1e-12
        else 0.0
    )
    blockers: list[str] = []
    notes: list[str] = []
    conditional_overlay_detected = bool(conditional_keys or model_token_folds)
    if conditional_overlay_detected:
        blockers.append("conditional_winner_refill_overlay_requires_shadow_holdout_review")
        notes.append("conditional_after_selection_winner_refill_rule_detected")
    if conditional_overlay_detected and len(positive_deltas) <= 3:
        notes.append("return_improvement_is_concentrated_in_three_or_fewer_folds")
    if conditional_overlay_detected and top_share >= 0.60:
        notes.append("largest_improvement_fold_contributes_at_least_60pct_of_positive_delta")
    status = "requires_shadow_holdout_review" if blockers else "pass"
    return {
        "status": status,
        "conditional_overlay_detected": conditional_overlay_detected,
        "conditional_overlay_keys": conditional_keys,
        "conditional_model_token": "wfWinPyrMinExtAS" if model_token_folds else None,
        "conditional_model_token_folds": model_token_folds,
        "changed_fold_count": len(changed_folds),
        "changed_folds": changed_folds,
        "positive_delta_fold_count": len(positive_deltas),
        "positive_delta_folds": [fold for fold, _ in positive_deltas],
        "top_positive_delta_fold": top_fold[0] if top_fold else None,
        "top_positive_delta_pct": _pct(top_fold[1]) if top_fold else 0.0,
        "top_positive_delta_share": _pct(top_share),
        "fold_deltas": fold_rows,
        "blockers": blockers,
        "notes": notes,
        "next_action": (
            "run_or_attach_independent_shadow_holdout_before_paper_or_live_promotion"
            if blockers
            else "no_overfit_holdout_blocker_detected"
        ),
        "no_live_order_sent": True,
    }


def _decision(
    *,
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    min_formal_folds: int,
    max_return_giveback_pct: float,
    max_drawdown_increase_pct: float,
    max_cost_increase_pct: float,
    lineage: dict[str, Any],
    lineage_policy: str,
) -> tuple[str, list[str], list[str]]:
    reasons: list[str] = []
    next_actions: list[str] = []
    if bool(lineage.get("failed")):
        return (
            "reject_lineage_failed",
            ["source_replay_lineage_guard_failed"],
            ["fix_lineage_or_run_as_explicit_new_candidate_before_any_promotion"],
        )
    if (
        int(lineage.get("unresolved_material_drift_count") or 0) > 0
        and lineage_policy != "explicit_new_candidate"
    ):
        return (
            "retune_or_reject_current_recipe",
            ["source_replay_unresolved_material_drift"],
            ["restore_source_replay_lineage_before_formal_promotion"],
        )

    fold_count = int(candidate.get("fold_count") or 0)
    return_delta = _float(candidate.get("return_delta_vs_baseline_pct"))
    drawdown_delta = _float(candidate.get("drawdown_delta_vs_baseline_pct"))
    cost_delta = _float(candidate.get("cost_delta_vs_baseline_pct"))
    positive_folds = int(candidate.get("positive_fold_count") or 0)
    flag_counts = dict(candidate.get("flag_counts") or {})

    if fold_count <= 0:
        return "missing_candidate_folds", ["no_common_folds"], ["run_shadow_wfo_candidate"]
    if positive_folds < fold_count:
        reasons.append("non_positive_fold_present")
    if return_delta < -abs(max_return_giveback_pct):
        reasons.append("return_giveback_exceeds_gate")
    if drawdown_delta > abs(max_drawdown_increase_pct):
        reasons.append("drawdown_increase_exceeds_gate")
    if cost_delta > abs(max_cost_increase_pct):
        reasons.append("cost_increase_exceeds_gate")
    if flag_counts:
        reasons.append("event_health_flags_present")

    if reasons:
        next_actions.extend(
            [
                "retune_recipe_before_formal_wfo",
                "compare_mode_returns_and_role_share_against_baseline",
            ]
        )
        return "retune_or_reject_current_recipe", reasons, next_actions

    if fold_count < max(1, int(min_formal_folds)):
        return (
            "smoke_pass_run_formal_wfo",
            ["common_fold_non_regression_passed"],
            ["run_full_shadow_wfo_with_warm_selection_state"],
        )

    return (
        "promotion_candidate_after_formal_wfo",
        ["formal_common_fold_non_regression_passed"],
        ["feed_candidate_into_live_readiness_and_paper_parity_gates"],
    )


def _decision_rank(decision: Any) -> int:
    ranks = {
        "promotion_candidate_after_formal_wfo": 0,
        "smoke_pass_run_formal_wfo": 1,
        "retune_or_reject_current_recipe": 2,
        "reject_lineage_failed": 3,
        "missing_candidate_folds": 4,
    }
    return ranks.get(str(decision), 9)


def _recipe_preference_rank(recipe_id: Any) -> int:
    recipe = str(recipe_id or "")
    if recipe in CANONICAL_RECIPE_IDS:
        return 0
    if any(marker in recipe for marker in EXPERIMENTAL_RECIPE_MARKERS):
        return 2
    return 1


def _recipe_tiebreak_key(item: dict[str, Any]) -> tuple[int, str]:
    recipe = str(item.get("recipe_id") or "")
    return (_recipe_preference_rank(recipe), recipe)


def _base_recipe_id(recipe_id: Any) -> str:
    recipe = str(recipe_id or "")
    if recipe.endswith("_formal"):
        return recipe[: -len("_formal")]
    return recipe


def _candidate_metric_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    candidate = dict(item.get("candidate") or {})
    audit = dict(item.get("execution_change_audit") or {})
    return (
        tuple(candidate.get("folds") or []),
        _pct(audit.get("return_delta_vs_baseline_pct")),
        _pct(audit.get("drawdown_delta_vs_baseline_pct")),
        _pct(audit.get("cost_delta_vs_baseline_pct")),
        int(audit.get("trade_event_delta_vs_baseline") or 0),
    )


def _formal_counterparts_by_base(
    items: list[dict[str, Any]],
    min_formal_folds: int,
) -> dict[str, dict[str, Any]]:
    counterparts: dict[str, dict[str, Any]] = {}
    for item in items:
        if not _has_formal_evidence(item, min_formal_folds):
            continue
        recipe = str(item.get("recipe_id") or "")
        if not recipe.endswith("_formal"):
            continue
        counterparts[_base_recipe_id(recipe)] = item
    return counterparts


def _candidate_fold_count(item: dict[str, Any]) -> int:
    return int(dict(item.get("candidate") or {}).get("fold_count") or 0)


def _has_formal_evidence(item: dict[str, Any], min_formal_folds: int) -> bool:
    return _candidate_fold_count(item) >= max(1, int(min_formal_folds))


def _is_formal_promotion(item: dict[str, Any], min_formal_folds: int) -> bool:
    return (
        str(item.get("decision") or "") == "promotion_candidate_after_formal_wfo"
        and _has_formal_evidence(item, min_formal_folds)
    )


def _is_smoke_ready(item: dict[str, Any], min_formal_folds: int) -> bool:
    return (
        str(item.get("decision") or "") == "smoke_pass_run_formal_wfo"
        and not _has_formal_evidence(item, min_formal_folds)
    )


def _routing_candidate_summary(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    candidate = dict(item.get("candidate") or {})
    audit = dict(item.get("execution_change_audit") or {})
    lineage = dict(item.get("lineage") or {})
    overfit_audit = dict(item.get("overfit_audit") or {})
    return {
        "recipe_id": item.get("recipe_id"),
        "decision": item.get("decision"),
        "report_path": item.get("report_path"),
        "fold_count": int(candidate.get("fold_count") or 0),
        "compounded_return_pct": _pct(candidate.get("compounded_return_pct")),
        "max_drawdown_pct": _pct(candidate.get("max_drawdown_pct")),
        "avg_cost_drag_pct": _pct(candidate.get("avg_cost_drag_pct")),
        "return_delta_vs_baseline_pct": _pct(audit.get("return_delta_vs_baseline_pct")),
        "return_giveback_fraction_vs_baseline": _pct(
            audit.get("return_giveback_fraction_vs_baseline")
        ),
        "drawdown_delta_vs_baseline_pct": _pct(audit.get("drawdown_delta_vs_baseline_pct")),
        "drawdown_reduction_fraction_vs_baseline": _pct(
            audit.get("drawdown_reduction_fraction_vs_baseline")
        ),
        "cost_delta_vs_baseline_pct": _pct(audit.get("cost_delta_vs_baseline_pct")),
        "risk_adjusted_compression_ready": bool(audit.get("risk_adjusted_compression_ready")),
        "lineage_guard_status": lineage.get("guard_status"),
        "lineage_unresolved_material_drift_count": int(
            lineage.get("unresolved_material_drift_count") or 0
        ),
        "lineage_unresolved_material_folds": list(lineage.get("unresolved_material_folds") or []),
        "lineage_review_packet": dict(item.get("lineage_review_packet") or {}),
        "overfit_audit_status": overfit_audit.get("status"),
        "overfit_audit_blockers": list(overfit_audit.get("blockers") or []),
        "overfit_audit": overfit_audit,
    }


def _defensive_lineage_review(defensive: dict[str, Any]) -> dict[str, Any]:
    guard_status = defensive.get("lineage_guard_status")
    drift_count = int(defensive.get("lineage_unresolved_material_drift_count") or 0)
    unresolved_folds = list(defensive.get("lineage_unresolved_material_folds") or [])
    review_required = bool(guard_status and guard_status != "pass") or drift_count > 0
    blockers: list[str] = []
    if guard_status and guard_status != "pass":
        blockers.append(f"defensive_lineage_guard_{guard_status}")
    if drift_count > 0:
        blockers.append("defensive_unresolved_material_drift")
    return {
        "required": review_required,
        "status": "pending_operator_lineage_review" if review_required else "not_required",
        "guard_status": guard_status,
        "unresolved_material_drift_count": drift_count,
        "unresolved_material_folds": unresolved_folds,
        "blockers": blockers,
        "review_packet": dict(defensive.get("lineage_review_packet") or {}),
        "next_action": (
            "review_defensive_candidate_lineage_delta_before_route_activation"
            if review_required
            else "no_lineage_review_required_before_defensive_route_activation"
        ),
    }


def _candidate_switch_policy(
    *,
    primary_candidate: dict[str, Any] | None,
    risk_adjusted_candidate: dict[str, Any] | None,
    max_risk_adjusted_return_giveback_fraction: float,
    min_risk_adjusted_drawdown_reduction_fraction: float,
) -> dict[str, Any]:
    primary = _routing_candidate_summary(primary_candidate)
    defensive = _routing_candidate_summary(risk_adjusted_candidate)
    if not primary:
        return {
            "status": "blocked_no_primary_candidate",
            "default_route": None,
            "defensive_route": None,
            "auto_switch_allowed_now": False,
            "blockers": ["primary_candidate_missing"],
            "no_live_order_sent": True,
        }
    if not defensive:
        return {
            "status": "primary_only_no_defensive_variant",
            "default_route": "primary_return_candidate",
            "default_candidate": primary,
            "defensive_route": None,
            "auto_switch_allowed_now": False,
            "blockers": ["risk_adjusted_compression_candidate_missing"],
            "next_action": "continue_generating_defensive_variants_without_changing_primary_candidate",
            "no_live_order_sent": True,
        }
    defensive_lineage_review = _defensive_lineage_review(defensive)
    switch_allowed_after_gates = [
        "paper_readiness",
        "execution_parity",
    ]
    if bool(defensive_lineage_review.get("required")):
        switch_allowed_after_gates.append("defensive_lineage_review")
    switch_allowed_after_gates.append("operator_review")
    return {
        "status": "primary_return_default_with_defensive_variant_available",
        "default_route": "primary_return_candidate",
        "default_candidate": primary,
        "defensive_route": "risk_adjusted_compression_candidate",
        "defensive_candidate": defensive,
        "defensive_lineage_review": defensive_lineage_review,
        "auto_switch_allowed_now": False,
        "switch_allowed_after_gates": switch_allowed_after_gates,
        "activation_policy": "use_primary_by_default_and_activate_defensive_variant_only_for_capital_preservation_or_stress",
        "activation_conditions": [
            {
                "condition": "operator_capital_preservation_mode",
                "action": "route_new_paper_or_shadow_decisions_to_defensive_candidate",
            },
            {
                "condition": "runtime_drawdown_near_primary_wfo_limit",
                "primary_reference_drawdown_pct": primary.get("max_drawdown_pct"),
                "defensive_reference_drawdown_pct": defensive.get("max_drawdown_pct"),
                "action": "prefer_defensive_candidate_until_drawdown_pressure_normalizes",
            },
            {
                "condition": "runtime_cost_or_slippage_deteriorates",
                "defensive_cost_delta_vs_baseline_pct": defensive.get("cost_delta_vs_baseline_pct"),
                "action": "prefer_defensive_candidate_when_it_keeps_cost_delta_non_positive",
            },
        ],
        "research_gates": {
            "max_risk_adjusted_return_giveback_fraction": float(
                max_risk_adjusted_return_giveback_fraction
            ),
            "min_risk_adjusted_drawdown_reduction_fraction": float(
                min_risk_adjusted_drawdown_reduction_fraction
            ),
        },
        "next_action": (
            "keep_primary_candidate_as_default_and_resolve_defensive_lineage_review_after_parity_rows_exist"
            if bool(defensive_lineage_review.get("required"))
            else "keep_primary_candidate_as_default_and_validate_defensive_switch_after_parity_rows_exist"
        ),
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def build_meta_router_shadow_wfo_compare(
    *,
    source_report: dict[str, Any],
    candidate_reports: list[tuple[str, dict[str, Any], str]],
    input_source_report: str | None = None,
    shadow_wfo_root: str | None = None,
    min_formal_folds: int = 12,
    max_return_giveback_pct: float = 3.0,
    max_risk_adjusted_return_giveback_fraction: float = 0.10,
    min_risk_adjusted_drawdown_reduction_fraction: float = 0.15,
    max_drawdown_increase_pct: float = 1.0,
    max_cost_increase_pct: float = 1.0,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    baseline_by_fold = _folds_by_number(source_report)
    candidates: list[dict[str, Any]] = []
    for recipe_id, report, report_path in candidate_reports:
        candidate_by_fold = _folds_by_number(report)
        common_folds = sorted(set(baseline_by_fold) & set(candidate_by_fold))
        baseline_metrics = _metrics_for_folds(source_report, common_folds)
        candidate_metrics = _metrics_for_folds(report, common_folds)
        candidate_metrics["return_delta_vs_baseline_pct"] = _pct(
            _float(candidate_metrics.get("compounded_return_pct"))
            - _float(baseline_metrics.get("compounded_return_pct"))
        )
        candidate_metrics["drawdown_delta_vs_baseline_pct"] = _pct(
            _float(candidate_metrics.get("max_drawdown_pct"))
            - _float(baseline_metrics.get("max_drawdown_pct"))
        )
        candidate_metrics["cost_delta_vs_baseline_pct"] = _pct(
            _float(candidate_metrics.get("avg_cost_drag_pct"))
            - _float(baseline_metrics.get("avg_cost_drag_pct"))
        )
        candidate_metrics["trade_event_delta_vs_baseline"] = int(
            candidate_metrics.get("trade_like_events") or 0
        ) - int(baseline_metrics.get("trade_like_events") or 0)
        execution_change_audit = _execution_change_audit(
            candidate_metrics,
            baseline_metrics,
            max_return_giveback_pct=max_return_giveback_pct,
            max_risk_adjusted_return_giveback_fraction=(
                max_risk_adjusted_return_giveback_fraction
            ),
            min_risk_adjusted_drawdown_reduction_fraction=(
                min_risk_adjusted_drawdown_reduction_fraction
            ),
            max_drawdown_increase_pct=max_drawdown_increase_pct,
            max_cost_increase_pct=max_cost_increase_pct,
        )
        overfit_audit = _overfit_audit(
            report,
            baseline_by_fold=baseline_by_fold,
            candidate_by_fold=candidate_by_fold,
            common_folds=common_folds,
        )
        lineage = _lineage_status(report)
        lineage_policy = _lineage_policy(recipe_id)
        lineage_review_packet = _lineage_review_packet(
            lineage=lineage,
            baseline_by_fold=baseline_by_fold,
            candidate_by_fold=candidate_by_fold,
        )
        decision, reasons, next_actions = _decision(
            candidate=candidate_metrics,
            baseline=baseline_metrics,
            min_formal_folds=min_formal_folds,
            max_return_giveback_pct=max_return_giveback_pct,
            max_drawdown_increase_pct=max_drawdown_increase_pct,
            max_cost_increase_pct=max_cost_increase_pct,
            lineage=lineage,
            lineage_policy=lineage_policy,
        )
        candidates.append(
            {
                "recipe_id": recipe_id,
                "report_path": report_path,
                "recipe_preference_rank": _recipe_preference_rank(recipe_id),
                "decision": decision,
                "decision_reasons": reasons,
                "next_actions": next_actions,
                "lineage_policy": lineage_policy,
                "lineage": lineage,
                "lineage_review_packet": lineage_review_packet,
                "execution_change_audit": execution_change_audit,
                "overfit_audit": overfit_audit,
                "common_fold_baseline": baseline_metrics,
                "candidate": candidate_metrics,
            }
        )

    ranked = sorted(
        candidates,
        key=lambda item: (
            _decision_rank(item.get("decision")),
            -_float(dict(item.get("candidate") or {}).get("return_delta_vs_baseline_pct")),
            _float(dict(item.get("candidate") or {}).get("drawdown_delta_vs_baseline_pct")),
            _float(dict(item.get("candidate") or {}).get("cost_delta_vs_baseline_pct")),
            *_recipe_tiebreak_key(item),
        ),
    )
    best_candidate = ranked[0] if ranked else None
    formal_counterparts_by_base = _formal_counterparts_by_base(ranked, min_formal_folds)
    performance_upgrade_candidates = [
        item
        for item in ranked
        if dict(item.get("execution_change_audit") or {}).get("performance_upgrade_ready") is True
        and _is_formal_promotion(item, min_formal_folds)
    ]
    raw_performance_upgrade_smoke_candidates = [
        item
        for item in ranked
        if dict(item.get("execution_change_audit") or {}).get("performance_upgrade_ready") is True
        and _is_smoke_ready(item, min_formal_folds)
    ]
    invalidated_smoke_signatures = {
        _candidate_metric_signature(item)
        for item in raw_performance_upgrade_smoke_candidates
        if _recipe_preference_rank(item.get("recipe_id")) == 0
        and (
            formal := formal_counterparts_by_base.get(_base_recipe_id(item.get("recipe_id")))
        )
        and dict(formal.get("execution_change_audit") or {}).get("performance_upgrade_ready")
        is not True
    }
    performance_upgrade_invalidated_smoke_candidates = [
        item
        for item in raw_performance_upgrade_smoke_candidates
        if (
            (
                formal := formal_counterparts_by_base.get(_base_recipe_id(item.get("recipe_id")))
            )
            and dict(formal.get("execution_change_audit") or {}).get("performance_upgrade_ready")
            is not True
        )
        or _candidate_metric_signature(item) in invalidated_smoke_signatures
    ]
    invalidated_smoke_ids = {
        str(item.get("recipe_id") or "") for item in performance_upgrade_invalidated_smoke_candidates
    }
    performance_upgrade_smoke_candidates = [
        item
        for item in raw_performance_upgrade_smoke_candidates
        if str(item.get("recipe_id") or "") not in invalidated_smoke_ids
    ]
    performance_upgrade_ranked = sorted(
        performance_upgrade_candidates,
        key=lambda item: (
            _decision_rank(item.get("decision")),
            -_float(dict(item.get("candidate") or {}).get("return_delta_vs_baseline_pct")),
            _float(dict(item.get("candidate") or {}).get("drawdown_delta_vs_baseline_pct")),
            _float(dict(item.get("candidate") or {}).get("cost_delta_vs_baseline_pct")),
            *_recipe_tiebreak_key(item),
        ),
    )
    best_performance_upgrade_candidate = performance_upgrade_ranked[0] if performance_upgrade_ranked else None
    performance_upgrade_smoke_ranked = sorted(
        performance_upgrade_smoke_candidates,
        key=lambda item: (
            -_float(dict(item.get("candidate") or {}).get("return_delta_vs_baseline_pct")),
            _float(dict(item.get("candidate") or {}).get("drawdown_delta_vs_baseline_pct")),
            _float(dict(item.get("candidate") or {}).get("cost_delta_vs_baseline_pct")),
            *_recipe_tiebreak_key(item),
        ),
    )
    best_performance_upgrade_smoke_candidate = (
        performance_upgrade_smoke_ranked[0] if performance_upgrade_smoke_ranked else None
    )
    performance_upgrade_invalidated_smoke_ranked = sorted(
        performance_upgrade_invalidated_smoke_candidates,
        key=lambda item: (
            -_float(dict(item.get("candidate") or {}).get("return_delta_vs_baseline_pct")),
            _float(dict(item.get("candidate") or {}).get("drawdown_delta_vs_baseline_pct")),
            _float(dict(item.get("candidate") or {}).get("cost_delta_vs_baseline_pct")),
            *_recipe_tiebreak_key(item),
        ),
    )
    best_performance_upgrade_invalidated_smoke_candidate = (
        performance_upgrade_invalidated_smoke_ranked[0]
        if performance_upgrade_invalidated_smoke_ranked
        else None
    )
    risk_compression_candidates = [
        item
        for item in ranked
        if dict(item.get("execution_change_audit") or {}).get("risk_compression_ready") is True
        and _is_formal_promotion(item, min_formal_folds)
    ]
    risk_compression_smoke_candidates = [
        item
        for item in ranked
        if dict(item.get("execution_change_audit") or {}).get("risk_compression_ready") is True
        and _is_smoke_ready(item, min_formal_folds)
    ]
    risk_adjusted_compression_candidates = [
        item
        for item in ranked
        if dict(item.get("execution_change_audit") or {}).get("risk_adjusted_compression_ready") is True
        and _has_formal_evidence(item, min_formal_folds)
    ]
    risk_adjusted_compression_smoke_candidates = [
        item
        for item in ranked
        if dict(item.get("execution_change_audit") or {}).get("risk_adjusted_compression_ready") is True
        and _is_smoke_ready(item, min_formal_folds)
    ]
    risk_compression_formal_tradeoffs = [
        item
        for item in ranked
        if dict(item.get("execution_change_audit") or {}).get("risk_compression_detected") is True
        and _has_formal_evidence(item, min_formal_folds)
        and dict(item.get("execution_change_audit") or {}).get("risk_compression_ready") is not True
    ]
    risk_compression_tradeoffs = [
        item
        for item in ranked
        if dict(item.get("execution_change_audit") or {}).get("risk_compression_detected") is True
    ]
    risk_compression_ranked = sorted(
        risk_compression_candidates,
        key=lambda item: (
            _decision_rank(item.get("decision")),
            _float(dict(item.get("candidate") or {}).get("drawdown_delta_vs_baseline_pct")),
            _float(dict(item.get("candidate") or {}).get("cost_delta_vs_baseline_pct")),
            -_float(dict(item.get("candidate") or {}).get("return_delta_vs_baseline_pct")),
            *_recipe_tiebreak_key(item),
        ),
    )
    risk_compression_tradeoff_ranked = sorted(
        risk_compression_tradeoffs,
        key=lambda item: (
            0 if _has_formal_evidence(item, min_formal_folds) else 1,
            0 if dict(item.get("execution_change_audit") or {}).get("risk_compression_ready") else 1,
            _float(dict(item.get("candidate") or {}).get("drawdown_delta_vs_baseline_pct")),
            _float(dict(item.get("candidate") or {}).get("cost_delta_vs_baseline_pct")),
            -_float(dict(item.get("candidate") or {}).get("return_delta_vs_baseline_pct")),
            *_recipe_tiebreak_key(item),
        ),
    )
    risk_compression_smoke_ranked = sorted(
        risk_compression_smoke_candidates,
        key=lambda item: (
            _float(dict(item.get("candidate") or {}).get("drawdown_delta_vs_baseline_pct")),
            _float(dict(item.get("candidate") or {}).get("cost_delta_vs_baseline_pct")),
            -_float(dict(item.get("candidate") or {}).get("return_delta_vs_baseline_pct")),
            *_recipe_tiebreak_key(item),
        ),
    )
    risk_adjusted_compression_ranked = sorted(
        risk_adjusted_compression_candidates,
        key=lambda item: (
            _float(
                dict(item.get("execution_change_audit") or {}).get(
                    "return_giveback_fraction_vs_baseline"
                )
            ),
            -_float(
                dict(item.get("execution_change_audit") or {}).get(
                    "drawdown_reduction_fraction_vs_baseline"
                )
            ),
            _float(dict(item.get("candidate") or {}).get("cost_delta_vs_baseline_pct")),
            *_recipe_tiebreak_key(item),
        ),
    )
    risk_adjusted_compression_smoke_ranked = sorted(
        risk_adjusted_compression_smoke_candidates,
        key=lambda item: (
            _float(
                dict(item.get("execution_change_audit") or {}).get(
                    "return_giveback_fraction_vs_baseline"
                )
            ),
            -_float(
                dict(item.get("execution_change_audit") or {}).get(
                    "drawdown_reduction_fraction_vs_baseline"
                )
            ),
            _float(dict(item.get("candidate") or {}).get("cost_delta_vs_baseline_pct")),
            *_recipe_tiebreak_key(item),
        ),
    )
    best_risk_compression_candidate = risk_compression_ranked[0] if risk_compression_ranked else None
    best_risk_compression_smoke_candidate = (
        risk_compression_smoke_ranked[0] if risk_compression_smoke_ranked else None
    )
    best_risk_adjusted_compression_candidate = (
        risk_adjusted_compression_ranked[0] if risk_adjusted_compression_ranked else None
    )
    best_risk_adjusted_compression_smoke_candidate = (
        risk_adjusted_compression_smoke_ranked[0]
        if risk_adjusted_compression_smoke_ranked
        else None
    )
    best_risk_compression_tradeoff = (
        risk_compression_tradeoff_ranked[0] if risk_compression_tradeoff_ranked else None
    )
    candidate_switch_policy = _candidate_switch_policy(
        primary_candidate=best_candidate,
        risk_adjusted_candidate=best_risk_adjusted_compression_candidate,
        max_risk_adjusted_return_giveback_fraction=max_risk_adjusted_return_giveback_fraction,
        min_risk_adjusted_drawdown_reduction_fraction=min_risk_adjusted_drawdown_reduction_fraction,
    )
    best_decision = str(dict(best_candidate or {}).get("decision") or "")
    best_overfit_blockers = list(
        dict(dict(best_candidate or {}).get("overfit_audit") or {}).get("blockers") or []
    )
    next_action = (
        "Run or attach an independent shadow holdout before live-readiness promotion for the best candidate."
        if best_overfit_blockers
        else (
        "Feed the formal non-regressing candidate into live readiness and paper parity gates."
        if best_decision == "promotion_candidate_after_formal_wfo"
        else "Run the best non-regressing candidate as formal WFO, or retune recipes when all candidates give back return."
        )
    )
    best_performance_overfit_blockers = list(
        dict(dict(best_performance_upgrade_candidate or {}).get("overfit_audit") or {}).get("blockers") or []
    )
    performance_upgrade_status = (
        "performance_upgrade_candidate_pending_holdout_review"
        if best_performance_upgrade_candidate and best_performance_overfit_blockers
        else (
        "performance_upgrade_candidate_available"
        if best_performance_upgrade_candidate
        else (
            "performance_upgrade_smoke_candidate_requires_formal_wfo"
            if best_performance_upgrade_smoke_candidate
            else (
                "performance_upgrade_smoke_candidate_failed_formal_wfo"
                if best_performance_upgrade_invalidated_smoke_candidate
                else "no_performance_upgrade_candidate_found"
            )
        )
        )
    )
    performance_upgrade_next_action = (
        "Run or attach independent shadow holdout before treating this conditional performance-upgrade candidate as promotable."
        if best_performance_upgrade_candidate and best_performance_overfit_blockers
        else (
        "Run live-readiness only after the performance-upgrade candidate also passes formal WFO and execution parity gates."
        if best_performance_upgrade_candidate
        else (
            "Run formal WFO before treating the smoke performance-upgrade candidate as available."
            if best_performance_upgrade_smoke_candidate
            else (
                "Retune the smoke performance-upgrade recipe; its formal counterpart failed the full WFO gates."
                if best_performance_upgrade_invalidated_smoke_candidate
                else "Generate execution-changing recipes; current candidates are either decomposition-only or give back return/risk/cost."
            )
        )
        )
    )
    risk_compression_status = (
        "risk_compression_candidate_available"
        if best_risk_compression_candidate
        else (
            "risk_compression_formal_tradeoff_found_but_return_giveback_exceeds_gate"
            if risk_compression_formal_tradeoffs
            else (
                "risk_compression_smoke_candidate_requires_formal_wfo"
                if best_risk_compression_smoke_candidate
                else (
                    "risk_compression_tradeoff_found_but_return_giveback_exceeds_gate"
                    if best_risk_compression_tradeoff
                    else "no_risk_compression_candidate_found"
                )
            )
        )
    )
    risk_compression_next_action = (
        "Feed the formal risk-compression candidate into readiness/parity gates before using it as a lower-volatility variant."
        if best_risk_compression_candidate
        else (
            "Retune the formal risk-compression recipe to recover return while preserving lower drawdown and acceptable cost."
            if risk_compression_formal_tradeoffs
            else (
                "Run formal WFO before using the smoke risk-compression candidate as a lower-volatility variant."
                if best_risk_compression_smoke_candidate
                else (
                    "Retune the risk-compression recipe to recover return while preserving lower drawdown and cost."
                    if best_risk_compression_tradeoff
                    else "Generate risk-compression recipes that lower drawdown/cost without exceeding the return giveback gate."
                )
            )
        )
    )
    risk_adjusted_compression_status = (
        "risk_adjusted_compression_candidate_available"
        if best_risk_adjusted_compression_candidate
        else (
            "risk_adjusted_compression_smoke_candidate_requires_formal_wfo"
            if best_risk_adjusted_compression_smoke_candidate
            else "no_risk_adjusted_compression_candidate_found"
        )
    )
    risk_adjusted_compression_next_action = (
        "Keep the primary return candidate unchanged; route this as an optional lower-drawdown variant after readiness/parity gates."
        if best_risk_adjusted_compression_candidate
        else (
            "Run formal WFO before treating the smoke risk-adjusted compression candidate as available."
            if best_risk_adjusted_compression_smoke_candidate
            else "Retune stability recipes until relative return giveback and drawdown reduction both clear the gate."
        )
    )
    return {
        "generated_at": generated_at.isoformat(),
        "status": "meta_router_shadow_wfo_compare_complete",
        "no_live_order_sent": True,
        "input_source_report": input_source_report,
        "shadow_wfo_root": shadow_wfo_root,
        "candidate_count": len(candidates),
        "safety_policy": {
            "research_only": True,
            "paper_or_live_execution": False,
            "live_allowed_candidate_count": 0,
            "requires_formal_wfo_before_readiness_promotion": True,
        },
        "gates": {
            "min_formal_folds": int(min_formal_folds),
            "max_return_giveback_pct": float(max_return_giveback_pct),
            "max_risk_adjusted_return_giveback_fraction": float(
                max_risk_adjusted_return_giveback_fraction
            ),
            "min_risk_adjusted_drawdown_reduction_fraction": float(
                min_risk_adjusted_drawdown_reduction_fraction
            ),
            "max_drawdown_increase_pct": float(max_drawdown_increase_pct),
            "max_cost_increase_pct": float(max_cost_increase_pct),
        },
        "candidates": ranked,
        "best_candidate": best_candidate,
        "performance_upgrade_status": performance_upgrade_status,
        "performance_upgrade_candidate_count": len(performance_upgrade_candidates),
        "performance_upgrade_smoke_candidate_count": len(performance_upgrade_smoke_candidates),
        "performance_upgrade_invalidated_smoke_candidate_count": len(
            performance_upgrade_invalidated_smoke_candidates
        ),
        "best_performance_upgrade_candidate": best_performance_upgrade_candidate,
        "best_performance_upgrade_smoke_candidate": best_performance_upgrade_smoke_candidate,
        "best_performance_upgrade_invalidated_smoke_candidate": (
            best_performance_upgrade_invalidated_smoke_candidate
        ),
        "performance_upgrade_next_action": performance_upgrade_next_action,
        "risk_compression_status": risk_compression_status,
        "risk_compression_candidate_count": len(risk_compression_candidates),
        "risk_compression_smoke_candidate_count": len(risk_compression_smoke_candidates),
        "risk_compression_formal_tradeoff_count": len(risk_compression_formal_tradeoffs),
        "best_risk_compression_candidate": best_risk_compression_candidate,
        "best_risk_compression_smoke_candidate": best_risk_compression_smoke_candidate,
        "risk_compression_tradeoff_count": len(risk_compression_tradeoffs),
        "best_risk_compression_tradeoff": best_risk_compression_tradeoff,
        "risk_compression_next_action": risk_compression_next_action,
        "risk_adjusted_compression_status": risk_adjusted_compression_status,
        "risk_adjusted_compression_candidate_count": len(risk_adjusted_compression_candidates),
        "risk_adjusted_compression_smoke_candidate_count": len(
            risk_adjusted_compression_smoke_candidates
        ),
        "best_risk_adjusted_compression_candidate": best_risk_adjusted_compression_candidate,
        "best_risk_adjusted_compression_smoke_candidate": (
            best_risk_adjusted_compression_smoke_candidate
        ),
        "risk_adjusted_compression_next_action": risk_adjusted_compression_next_action,
        "candidate_switch_policy": candidate_switch_policy,
        "next_action": next_action,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Meta-Router Shadow WFO Compare",
        "",
        f"- status: `{report.get('status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- candidate_count: `{report.get('candidate_count')}`",
        f"- performance_upgrade_status: `{report.get('performance_upgrade_status')}`",
        f"- performance_upgrade_candidate_count: `{report.get('performance_upgrade_candidate_count')}`",
        f"- performance_upgrade_smoke_candidate_count: `{report.get('performance_upgrade_smoke_candidate_count')}`",
        f"- performance_upgrade_invalidated_smoke_candidate_count: `{report.get('performance_upgrade_invalidated_smoke_candidate_count')}`",
        f"- performance_upgrade_next_action: `{report.get('performance_upgrade_next_action')}`",
        f"- risk_compression_status: `{report.get('risk_compression_status')}`",
        f"- risk_compression_candidate_count: `{report.get('risk_compression_candidate_count')}`",
        f"- risk_compression_smoke_candidate_count: `{report.get('risk_compression_smoke_candidate_count')}`",
        f"- risk_compression_formal_tradeoff_count: `{report.get('risk_compression_formal_tradeoff_count')}`",
        f"- risk_compression_tradeoff_count: `{report.get('risk_compression_tradeoff_count')}`",
        f"- risk_compression_next_action: `{report.get('risk_compression_next_action')}`",
        f"- risk_adjusted_compression_status: `{report.get('risk_adjusted_compression_status')}`",
        f"- risk_adjusted_compression_candidate_count: `{report.get('risk_adjusted_compression_candidate_count')}`",
        f"- risk_adjusted_compression_smoke_candidate_count: `{report.get('risk_adjusted_compression_smoke_candidate_count')}`",
        f"- risk_adjusted_compression_next_action: `{report.get('risk_adjusted_compression_next_action')}`",
        f"- candidate_switch_policy_status: `{dict(report.get('candidate_switch_policy') or {}).get('status')}`",
        f"- candidate_switch_default_route: `{dict(report.get('candidate_switch_policy') or {}).get('default_route')}`",
        f"- candidate_switch_defensive_route: `{dict(report.get('candidate_switch_policy') or {}).get('defensive_route')}`",
        f"- candidate_switch_defensive_lineage_review_status: `{dict(dict(report.get('candidate_switch_policy') or {}).get('defensive_lineage_review') or {}).get('status')}`",
        f"- candidate_switch_defensive_lineage_review_summary: `{dict(dict(dict(report.get('candidate_switch_policy') or {}).get('defensive_lineage_review') or {}).get('review_packet') or {}).get('summary')}`",
        "",
        "## Candidates",
        "",
    ]
    for item in list(report.get("candidates") or []):
        candidate = dict(item.get("candidate") or {})
        execution_audit = dict(item.get("execution_change_audit") or {})
        overfit_audit = dict(item.get("overfit_audit") or {})
        lines.append(
            f"- `{item.get('recipe_id')}`: decision=`{item.get('decision')}`, "
            f"return_delta=`{candidate.get('return_delta_vs_baseline_pct')}`, "
            f"dd_delta=`{candidate.get('drawdown_delta_vs_baseline_pct')}`, "
            f"cost_delta=`{candidate.get('cost_delta_vs_baseline_pct')}`, "
            f"performance_upgrade_ready=`{execution_audit.get('performance_upgrade_ready')}`, "
            f"risk_compression_ready=`{execution_audit.get('risk_compression_ready')}`, "
            f"risk_adjusted_compression_ready=`{execution_audit.get('risk_adjusted_compression_ready')}`, "
            f"overfit_audit=`{overfit_audit.get('status')}`, "
            f"overfit_blockers=`{','.join(overfit_audit.get('blockers') or [])}`, "
            f"execution_delta_status=`{execution_audit.get('status')}`, "
            f"folds=`{candidate.get('folds')}`"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare v6 adaptive meta-router shadow WFO reports.")
    parser.add_argument("--source-report", default=DEFAULT_SOURCE_REPORT)
    parser.add_argument("--shadow-wfo-root", default=DEFAULT_SHADOW_WFO_ROOT)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--min-formal-folds", type=int, default=12)
    parser.add_argument("--max-return-giveback-pct", type=float, default=3.0)
    parser.add_argument("--max-risk-adjusted-return-giveback-fraction", type=float, default=0.10)
    parser.add_argument("--min-risk-adjusted-drawdown-reduction-fraction", type=float, default=0.15)
    parser.add_argument("--max-drawdown-increase-pct", type=float, default=1.0)
    parser.add_argument("--max-cost-increase-pct", type=float, default=1.0)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = _resolve(args.source_report)
    candidate_reports = [
        (path.parent.name, _load_json(path), _display_path(path) or str(path))
        for path in _candidate_report_paths(args.shadow_wfo_root)
    ]
    report = build_meta_router_shadow_wfo_compare(
        source_report=_load_json(args.source_report),
        candidate_reports=candidate_reports,
        input_source_report=_display_path(source_path),
        shadow_wfo_root=args.shadow_wfo_root,
        min_formal_folds=max(1, int(args.min_formal_folds)),
        max_return_giveback_pct=max(0.0, float(args.max_return_giveback_pct)),
        max_risk_adjusted_return_giveback_fraction=max(
            0.0,
            float(args.max_risk_adjusted_return_giveback_fraction),
        ),
        min_risk_adjusted_drawdown_reduction_fraction=max(
            0.0,
            float(args.min_risk_adjusted_drawdown_reduction_fraction),
        ),
        max_drawdown_increase_pct=max(0.0, float(args.max_drawdown_increase_pct)),
        max_cost_increase_pct=max(0.0, float(args.max_cost_increase_pct)),
    )
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        assert report_dir is not None
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_meta_router_shadow_wfo_compare.json"
        md_path = report_dir / "market_state_rotation_v6_meta_router_shadow_wfo_compare.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
