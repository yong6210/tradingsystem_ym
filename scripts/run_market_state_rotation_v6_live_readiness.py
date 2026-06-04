#!/usr/bin/env python3
"""Assess practical live readiness for market-state rotation v6.

The walk-forward and stress reports can show strong historical return while
still failing practical deployment constraints. This script turns those reports
into explicit gates so a profile cannot be treated as full-live ready while
cost/funding, concentration, or missing evidence remains unresolved.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(value: float) -> float:
    return round(float(value), 4)


def _safe_equity(return_pct: float) -> float:
    return max(1.0 + float(return_pct) / 100.0, 1e-12)


def _gate(name: str, passed: bool, *, value: Any, threshold: Any, severity: str = "blocker") -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "value": value,
        "threshold": threshold,
        "severity": severity,
    }


def _combined_monthly_returns(walk_report: dict[str, Any]) -> list[dict[str, Any]]:
    monthly_values: dict[str, list[float]] = {}
    for fold in walk_report.get("folds") or []:
        result = dict(fold.get("test_result") or {})
        monthly = dict(result.get("monthly") or {})
        for month, value in dict(monthly.get("monthly_returns") or {}).items():
            monthly_values.setdefault(str(month), []).append(_float(value))
    rows: list[dict[str, Any]] = []
    for month, values in sorted(monthly_values.items()):
        equity = 1.0
        for value in values:
            equity *= max(1.0 + value, 1e-12)
        rows.append(
            {
                "month": month,
                "return_pct": _pct((equity - 1.0) * 100.0),
                "source_count": len(values),
            }
        )
    return rows


def _hour_key(value: Any) -> str | None:
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return None
    if hour < 0 or hour > 23:
        return None
    return f"{hour:02d}"


def _rolling_month_returns(monthly_rows: list[dict[str, Any]], window: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if window <= 0 or len(monthly_rows) < window:
        return rows
    for idx in range(0, len(monthly_rows) - window + 1):
        chunk = monthly_rows[idx : idx + window]
        equity = 1.0
        for row in chunk:
            equity *= _safe_equity(_float(row.get("return_pct")))
        rows.append(
            {
                "start_month": chunk[0].get("month"),
                "end_month": chunk[-1].get("month"),
                "return_pct": _pct((equity - 1.0) * 100.0),
            }
        )
    return rows


def _calendar_rolling_summary(walk_report: dict[str, Any]) -> dict[str, Any]:
    required_windows = ("30d", "60d", "90d")
    rows_by_window: dict[str, list[dict[str, Any]]] = {window: [] for window in required_windows}
    fold_rows: list[dict[str, Any]] = []
    missing_folds: list[dict[str, Any]] = []
    folds = list(walk_report.get("folds") or [])

    for fold in folds:
        fold_id = int(fold.get("fold") or 0)
        result = dict(fold.get("test_result") or {})
        calendar = dict(result.get("calendar_rolling") or {})
        windows = dict(calendar.get("windows") or {})
        fold_row: dict[str, Any] = {
            "fold": fold_id,
            "daily_count": int(calendar.get("daily_count") or 0),
        }
        missing_windows: list[str] = []
        for window in required_windows:
            payload = dict(windows.get(window) or {})
            count = int(payload.get("count") or 0)
            min_return = payload.get("min_return_pct")
            available = count > 0 and min_return is not None
            fold_row[window] = {
                "available": available,
                "count": count,
                "min_return_pct": _pct(_float(min_return)) if min_return is not None else None,
                "worst_window": dict(payload.get("worst_window") or {}),
            }
            if available:
                rows_by_window[window].append(
                    {
                        "fold": fold_id,
                        "count": count,
                        "min_return_pct": _pct(_float(min_return)),
                        "worst_window": dict(payload.get("worst_window") or {}),
                    }
                )
            else:
                missing_windows.append(window)
        if missing_windows:
            missing_folds.append({"fold": fold_id, "missing_windows": missing_windows})
        fold_rows.append(fold_row)

    summary_windows: dict[str, dict[str, Any]] = {}
    for window, rows in rows_by_window.items():
        worst = min(rows, key=lambda item: _float(item.get("min_return_pct")), default={})
        summary_windows[window] = {
            "fold_count_with_window": len(rows),
            "worst_min_return_pct": _pct(_float(worst.get("min_return_pct"))) if worst else None,
            "worst_fold": int(worst.get("fold") or 0) if worst else None,
            "worst_window": dict(worst.get("worst_window") or {}),
        }

    return {
        "required_windows": list(required_windows),
        "all_windows_available": bool(folds) and not missing_folds,
        "missing_folds": missing_folds,
        "windows": summary_windows,
        "folds": fold_rows,
    }


def _aggregate_kst_hour_realized_pnl(walk_report: dict[str, Any]) -> dict[str, Any]:
    pnl_by_hour: dict[str, float] = {}
    remove_by_hour: dict[str, int] = {}
    missing_folds: list[int] = []
    folds = list(walk_report.get("folds") or [])

    for fold in folds:
        diagnostics = dict(dict(fold.get("test_result") or {}).get("event_diagnostics") or {})
        pnl_payload = diagnostics.get("realized_pnl_usd_units_by_kst_hour")
        remove_payload = diagnostics.get("remove_by_kst_hour")
        if not isinstance(pnl_payload, dict) or not isinstance(remove_payload, dict):
            missing_folds.append(int(fold.get("fold") or 0))
            continue
        for hour, value in pnl_payload.items():
            key = _hour_key(hour)
            if key is not None:
                pnl_by_hour[key] = pnl_by_hour.get(key, 0.0) + _float(value)
        for hour, count in remove_payload.items():
            key = _hour_key(hour)
            if key is not None:
                remove_by_hour[key] = remove_by_hour.get(key, 0) + int(count or 0)

    avg_by_hour = {
        hour: round(pnl_by_hour.get(hour, 0.0) / max(remove_by_hour.get(hour, 0), 1), 4)
        for hour in sorted(set(pnl_by_hour) | set(remove_by_hour))
    }
    worst_hour = min(avg_by_hour.items(), key=lambda item: item[1], default=(None, 0.0))
    best_hour = max(avg_by_hour.items(), key=lambda item: item[1], default=(None, 0.0))
    return {
        "available": bool(folds) and not missing_folds,
        "missing_folds": missing_folds,
        "remove_by_kst_hour": {hour: int(count) for hour, count in sorted(remove_by_hour.items())},
        "realized_pnl_usd_units_by_kst_hour": {
            hour: _pct(value)
            for hour, value in sorted(pnl_by_hour.items())
        },
        "realized_pnl_usd_units_per_remove_by_kst_hour": avg_by_hour,
        "worst_avg_pnl_kst_hour": worst_hour[0],
        "worst_avg_pnl_usd_units": _pct(worst_hour[1]),
        "best_avg_pnl_kst_hour": best_hour[0],
        "best_avg_pnl_usd_units": _pct(best_hour[1]),
    }


def _fold_rows(walk_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fold in walk_report.get("folds") or []:
        result = dict(fold.get("test_result") or {})
        diagnostics = dict(result.get("event_diagnostics") or {})
        rows.append(
            {
                "fold": int(fold.get("fold") or 0),
                "test_start": fold.get("test_start"),
                "test_end": fold.get("test_end"),
                "return_pct": _pct(_float(result.get("total_return_pct"))),
                "drawdown_pct": _pct(_float(result.get("max_drawdown_pct"))),
                "cost_drag_pct": _pct(_float(result.get("estimated_cost_drag_pct"))),
                "trade_like_events": int(result.get("trade_like_events") or 0),
                "health": diagnostics.get("health"),
                "flags": list(diagnostics.get("flags") or []),
                "max_kst_hour_add_share": _float(diagnostics.get("max_kst_hour_add_share")),
                "max_month_add_share": _float(diagnostics.get("max_month_add_share")),
                "max_role_add_share": _float(diagnostics.get("max_role_add_share")),
            }
        )
    return rows


def _aggregate_kst_hour_adds(walk_report: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for fold in walk_report.get("folds") or []:
        diagnostics = dict(dict(fold.get("test_result") or {}).get("event_diagnostics") or {})
        for hour, count in dict(diagnostics.get("add_by_kst_hour") or {}).items():
            counts[f"{int(hour):02d}"] = counts.get(f"{int(hour):02d}", 0) + int(count or 0)
    total = sum(counts.values())
    shares = {
        hour: round(count / total, 4)
        for hour, count in sorted(counts.items())
        if total > 0
    }
    max_hour = max(shares.items(), key=lambda item: item[1]) if shares else (None, 0.0)
    return {
        "total_adds": total,
        "active_kst_hours": len(counts),
        "add_by_kst_hour": dict(sorted(counts.items())),
        "add_share_by_kst_hour": shares,
        "dominant_kst_hour": max_hour[0],
        "max_kst_hour_add_share": max_hour[1],
    }


def _stress_rows(stress_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for name, payload in dict(stress_report.get("scenarios") or {}).items():
        summary = dict(payload.get("summary") or {})
        rows[str(name)] = {
            "compounded_return_pct": _float(summary.get("compounded_return_pct")),
            "avg_return_pct": _float(summary.get("avg_return_pct")),
            "min_return_pct": _float(summary.get("min_return_pct")),
            "max_drawdown_proxy_pct": _float(summary.get("max_drawdown_proxy_pct")),
            "max_actionable_drawdown_proxy_pct": _float(
                summary.get(
                    "max_actionable_drawdown_proxy_pct",
                    summary.get("max_drawdown_proxy_pct"),
                )
            ),
            "max_protected_alpha_drawdown_proxy_pct": _float(
                summary.get("max_protected_alpha_drawdown_proxy_pct")
            ),
            "protected_alpha_fold_count": int(summary.get("protected_alpha_fold_count") or 0),
            "stress_floor_gap_count": int(summary.get("stress_floor_gap_count") or 0),
            "max_stress_floor_gap_pct": _float(summary.get("max_stress_floor_gap_pct")),
            "actionable_drawdown_verdict": summary.get("actionable_drawdown_verdict"),
            "positive_fold_count": int(summary.get("positive_fold_count") or 0),
            "fold_count": int(summary.get("fold_count") or 0),
            "verdict": summary.get("verdict"),
            "remediation_priority_folds": [
                _compact_stress_priority_fold(row)
                for row in list(summary.get("remediation_priority_folds") or [])[:5]
                if isinstance(row, dict)
            ],
        }
    return rows


def _compact_stress_priority_fold(row: dict[str, Any]) -> dict[str, Any]:
    floor = dict(row.get("stress_floor") or {})
    return {
        "fold": int(row.get("fold") or 0),
        "test_start": row.get("test_start"),
        "test_end": row.get("test_end"),
        "stressed_return_pct": _pct(_float(row.get("stressed_return_pct"))),
        "drawdown_proxy_pct": _pct(_float(row.get("drawdown_proxy_pct"))),
        "stress_floor_gap_pct": _pct(_float(floor.get("gross_return_gain_needed_pct"))),
        "baseline_cost_reduction_needed_pct": (
            _pct(_float(floor.get("baseline_cost_reduction_needed_pct")))
            if floor.get("baseline_cost_reduction_needed_pct") is not None
            else None
        ),
        "target_baseline_cost_reduction_share": floor.get("target_baseline_cost_reduction_share"),
        "breakeven_cost_multiplier": row.get("breakeven_cost_multiplier"),
        "cost_to_gross_ratio": row.get("cost_to_gross_ratio"),
        "root_causes": list(row.get("root_causes") or [])[:6],
        "remediation_hints": list(row.get("remediation_hints") or [])[:6],
        "top_cost_reasons": list(row.get("top_cost_reasons") or [])[:3],
        "targeted_cost_reduction_plan": dict(row.get("targeted_cost_reduction_plan") or {}),
    }


def _execution_parity_summary(
    execution_parity_report: dict[str, Any] | None,
    *,
    expected_symbol: str = "",
    expected_strategy_family: str = "market_state_rotation_v6",
) -> dict[str, Any]:
    if not execution_parity_report:
        return {
            "available": False,
            "passed": False,
            "value": "not_attached_to_this_report",
            "blockers": ["execution_parity_report_missing"],
        }
    payload = dict(execution_parity_report)
    summary = dict(payload.get("summary") or payload)
    evaluation = dict(payload.get("evaluation") or {})
    filters = dict(dict(payload.get("active_contract") or {}).get("filters") or {})
    blockers = [
        str(item)
        for item in (
            summary.get("blockers")
            or summary.get("issues")
            or payload.get("blockers")
            or payload.get("issues")
            or []
        )
    ]
    observed_symbol = str(summary.get("symbol") or payload.get("symbol") or "").upper()
    if expected_symbol and observed_symbol and observed_symbol != str(expected_symbol).upper():
        blockers.append("execution_parity_symbol_mismatch")
    observed_families = {
        str(item)
        for item in (
            filters.get("strategy_families")
            or summary.get("strategy_families")
            or payload.get("strategy_families")
            or []
        )
        if str(item)
    }
    if expected_strategy_family and observed_families and expected_strategy_family not in observed_families:
        blockers.append("execution_parity_strategy_family_mismatch")
    explicit_status = summary.get("passed")
    if explicit_status is None:
        explicit_status = summary.get("ready")
    if explicit_status is None:
        status = str(
            summary.get("status")
            or summary.get("decision")
            or payload.get("overall_status")
            or evaluation.get("status")
            or ""
        ).lower()
        explicit_status = status in {"pass", "passed", "ready", "paper_ready", "live_ready"}
    sample_count = int(summary.get("sample_count") or summary.get("order_count") or 0)
    if sample_count <= 0:
        sample_count = int(
            summary.get("recent_live_intents")
            or summary.get("recent_live_submissions")
            or evaluation.get("recent_live_intents")
            or evaluation.get("recent_live_submissions")
            or 0
        )
    min_sample_count = int(summary.get("min_sample_count") or 0)
    reason = str(summary.get("reason") or evaluation.get("reason") or "")
    if (
        bool(evaluation.get("runtime_no_actionable_flow"))
        or reason
        in {
            "runtime_window_below_live_replay_parity_evidence_floor",
            "portfolio_runtime_window_below_live_replay_parity_evidence_floor",
        }
    ):
        blockers.append("runtime_window_below_execution_parity_evidence_floor")
    passed = bool(explicit_status) and not blockers and sample_count >= min_sample_count
    return {
        "available": True,
        "passed": passed,
        "value": {
            "status": (
                summary.get("status")
                or summary.get("decision")
                or payload.get("overall_status")
                or evaluation.get("status")
            ),
            "reason": reason or None,
            "sample_count": sample_count,
            "min_sample_count": min_sample_count,
            "order_match_rate": summary.get("order_match_rate"),
            "max_signal_lag_bars": summary.get("max_signal_lag_bars"),
            "max_position_diff_units": summary.get("max_position_diff_units"),
            "max_fee_slippage_bps": summary.get("max_fee_slippage_bps"),
            "live_vs_replay_flow_ratio": evaluation.get("live_vs_replay_flow_ratio"),
            "order_flow_status": evaluation.get("order_flow_status"),
            "order_flow_reason": evaluation.get("order_flow_reason"),
            "symbol": observed_symbol or None,
            "strategy_families": sorted(observed_families),
            "expected_symbol": str(expected_symbol).upper() if expected_symbol else None,
            "expected_strategy_family": expected_strategy_family,
        },
        "blockers": blockers,
        "contract": dict(payload.get("contract") or {}),
        "required_fields": dict(payload.get("required_fields") or {}),
    }


def _build_remediation_plan(
    *,
    blockers: list[str],
    warnings: list[str],
    stress: dict[str, dict[str, Any]],
    execution_parity: dict[str, Any],
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    if "live_or_paper_execution_parity_available" in blockers:
        plan.append(
            {
                "blocker": "live_or_paper_execution_parity_available",
                "status": "not_ready",
                "reason": "market_state_rotation_v6 paper/live execution journal has not passed the contract.",
                "current": execution_parity.get("value"),
                "nested_blockers": list(execution_parity.get("blockers") or []),
                "required_fields": dict(execution_parity.get("required_fields") or {}),
                "contract": dict(execution_parity.get("contract") or {}),
                "next_action": (
                    "Run paper execution until the contract has at least the required actionable samples, "
                    "with lineage ids, replay-vs-actual action/side, signal lag, position drift, and fee/slippage evidence."
                ),
            }
        )
    for name, row in stress.items():
        floor_blocker = f"{name}_min_return_floor"
        if floor_blocker not in blockers:
            continue
        plan.append(
            {
                "blocker": floor_blocker,
                "status": "not_ready",
                "current_min_return_pct": _pct(_float(row.get("min_return_pct"))),
                "target_min_return_pct": 5.0,
                "stress_floor_gap_count": int(row.get("stress_floor_gap_count") or 0),
                "max_stress_floor_gap_pct": _pct(_float(row.get("max_stress_floor_gap_pct"))),
                "priority_folds": list(row.get("remediation_priority_folds") or []),
                "next_action": (
                    "Prioritize the listed folds and test only targeted cost/turnover cuts before changing "
                    "the profitable base/chase alpha engine."
                ),
            }
        )
    if "all_exact_30d_windows_positive" in warnings or "all_exact_60d_windows_positive" in warnings:
        plan.append(
            {
                "blocker": "short_calendar_window_consistency",
                "status": "warning",
                "current": {
                    "all_exact_30d_windows_positive": "all_exact_30d_windows_positive" not in warnings,
                    "all_exact_60d_windows_positive": "all_exact_60d_windows_positive" not in warnings,
                },
                "next_action": (
                    "Keep the exact 30d/60d losing windows visible in paper review; they are within the hard loss cap "
                    "but not yet uniformly positive."
                ),
            }
        )
    return plan


def build_readiness_report(
    walk_report: dict[str, Any],
    stress_report: dict[str, Any],
    *,
    execution_parity_report: dict[str, Any] | None = None,
    input_walk_report: str | None = None,
    input_stress_report: str | None = None,
    input_execution_parity_report: str | None = None,
    min_fold_count: int = 16,
    min_fold_return_pct: float = 10.0,
    max_fold_drawdown_pct: float = 15.0,
    max_month_loss_pct: float = 7.5,
    min_rolling_3m_return_pct: float = 0.0,
    min_rolling_6m_return_pct: float = 10.0,
    max_exact_30d_loss_pct: float = 8.0,
    max_exact_60d_loss_pct: float = 8.0,
    min_exact_90d_return_pct: float = 0.0,
    max_kst_hour_add_share: float = 0.25,
    max_role_add_share: float = 0.90,
    stress_min_return_pct: float = 5.0,
    stress_max_drawdown_proxy_pct: float = 35.0,
    canary_drawdown_proxy_pct: float = 20.0,
) -> dict[str, Any]:
    aggregate = dict(walk_report.get("aggregate") or {})
    folds = _fold_rows(walk_report)
    monthly = _combined_monthly_returns(walk_report)
    rolling_3m = _rolling_month_returns(monthly, 3)
    rolling_6m = _rolling_month_returns(monthly, 6)
    stress = _stress_rows(stress_report)
    kst_hours = _aggregate_kst_hour_adds(walk_report)
    exact_rolling = _calendar_rolling_summary(walk_report)
    kst_hour_pnl = _aggregate_kst_hour_realized_pnl(walk_report)
    execution_parity = _execution_parity_summary(
        execution_parity_report,
        expected_symbol=str(walk_report.get("symbol") or ""),
    )

    fold_returns = [_float(row.get("return_pct")) for row in folds]
    fold_drawdowns = [_float(row.get("drawdown_pct")) for row in folds]
    max_role_share = max((_float(row.get("max_role_add_share")) for row in folds), default=0.0)
    fold_flags = [row for row in folds if row.get("flags")]
    non_ok_health = [row for row in folds if row.get("health") != "ok"]
    losing_months = [row for row in monthly if _float(row.get("return_pct")) < 0.0]
    worst_month = min(monthly, key=lambda item: _float(item.get("return_pct")), default={})
    worst_rolling_3m = min(rolling_3m, key=lambda item: _float(item.get("return_pct")), default={})
    worst_rolling_6m = min(rolling_6m, key=lambda item: _float(item.get("return_pct")), default={})
    exact_windows = dict(exact_rolling.get("windows") or {})
    exact_available = bool(exact_rolling.get("all_windows_available"))

    def exact_min_return(window: str) -> float | None:
        payload = dict(exact_windows.get(window) or {})
        value = payload.get("worst_min_return_pct")
        return _float(value) if value is not None else None

    oos_gates = [
        _gate("min_fold_count", len(folds) >= min_fold_count, value=len(folds), threshold=f">={min_fold_count}"),
        _gate(
            "all_oos_folds_positive",
            all(value > 0.0 for value in fold_returns),
            value=sum(1 for value in fold_returns if value > 0.0),
            threshold=f"{len(folds)}/{len(folds)}",
        ),
        _gate(
            "min_fold_return",
            min(fold_returns, default=0.0) >= min_fold_return_pct,
            value=_pct(min(fold_returns, default=0.0)),
            threshold=f">={min_fold_return_pct}",
        ),
        _gate(
            "max_fold_drawdown",
            max(fold_drawdowns, default=0.0) <= max_fold_drawdown_pct,
            value=_pct(max(fold_drawdowns, default=0.0)),
            threshold=f"<={max_fold_drawdown_pct}",
        ),
        _gate("all_fold_health_ok", not non_ok_health, value=len(non_ok_health), threshold="0"),
        _gate("no_fold_flags", not fold_flags, value=len(fold_flags), threshold="0", severity="warning"),
    ]
    calendar_gates = [
        _gate(
            "worst_month_loss_within_limit",
            abs(min(_float(row.get("return_pct")) for row in monthly) if monthly else 0.0) <= max_month_loss_pct,
            value=_pct(_float(worst_month.get("return_pct"))),
            threshold=f">=-{max_month_loss_pct}",
        ),
        _gate(
            "no_negative_3m_rolling_window",
            _float(worst_rolling_3m.get("return_pct")) >= min_rolling_3m_return_pct,
            value=_pct(_float(worst_rolling_3m.get("return_pct"))),
            threshold=f">={min_rolling_3m_return_pct}",
        ),
        _gate(
            "six_month_rolling_buffer",
            _float(worst_rolling_6m.get("return_pct")) >= min_rolling_6m_return_pct,
            value=_pct(_float(worst_rolling_6m.get("return_pct"))),
            threshold=f">={min_rolling_6m_return_pct}",
        ),
        _gate(
            "exact_30d_rolling_loss_within_limit",
            (not exact_available)
            or (
                exact_min_return("30d") is not None
                and float(exact_min_return("30d") or 0.0) >= -max_exact_30d_loss_pct
            ),
            value=(
                "not_evaluated_until_exact_rolling_available"
                if not exact_available
                else _pct(float(exact_min_return("30d") or 0.0))
            ),
            threshold=f">=-{max_exact_30d_loss_pct}",
        ),
        _gate(
            "exact_60d_rolling_loss_within_limit",
            (not exact_available)
            or (
                exact_min_return("60d") is not None
                and float(exact_min_return("60d") or 0.0) >= -max_exact_60d_loss_pct
            ),
            value=(
                "not_evaluated_until_exact_rolling_available"
                if not exact_available
                else _pct(float(exact_min_return("60d") or 0.0))
            ),
            threshold=f">=-{max_exact_60d_loss_pct}",
        ),
        _gate(
            "exact_90d_rolling_positive",
            (not exact_available)
            or (
                exact_min_return("90d") is not None
                and float(exact_min_return("90d") or 0.0) >= min_exact_90d_return_pct
            ),
            value=(
                "not_evaluated_until_exact_rolling_available"
                if not exact_available
                else _pct(float(exact_min_return("90d") or 0.0))
            ),
            threshold=f">={min_exact_90d_return_pct}",
        ),
        _gate(
            "all_exact_30d_windows_positive",
            (not exact_available)
            or (
                exact_min_return("30d") is not None
                and float(exact_min_return("30d") or 0.0) >= 0.0
            ),
            value=(
                "not_evaluated_until_exact_rolling_available"
                if not exact_available
                else _pct(float(exact_min_return("30d") or 0.0))
            ),
            threshold=">=0.0",
            severity="warning",
        ),
        _gate(
            "all_exact_60d_windows_positive",
            (not exact_available)
            or (
                exact_min_return("60d") is not None
                and float(exact_min_return("60d") or 0.0) >= 0.0
            ),
            value=(
                "not_evaluated_until_exact_rolling_available"
                if not exact_available
                else _pct(float(exact_min_return("60d") or 0.0))
            ),
            threshold=">=0.0",
            severity="warning",
        ),
        _gate(
            "kst_hour_add_concentration",
            _float(kst_hours.get("max_kst_hour_add_share")) <= max_kst_hour_add_share,
            value=_float(kst_hours.get("max_kst_hour_add_share")),
            threshold=f"<={max_kst_hour_add_share}",
            severity="warning",
        ),
        _gate(
            "role_add_concentration",
            max_role_share <= max_role_add_share,
            value=round(max_role_share, 4),
            threshold=f"<={max_role_add_share}",
            severity="warning",
        ),
    ]

    required_stress = [
        name
        for name in ("fee6_slip2", "fee6_slip4", "cost_x2_funding3", "cost_x3_funding3")
        if name in stress
    ]
    stress_gates: list[dict[str, Any]] = []
    for name in required_stress:
        row = stress[name]
        raw_dd = _float(row.get("max_drawdown_proxy_pct"))
        actionable_dd = _float(row.get("max_actionable_drawdown_proxy_pct"), raw_dd)
        protected_alpha_count = int(row.get("protected_alpha_fold_count") or 0)
        stress_gates.extend(
            [
                _gate(
                    f"{name}_all_folds_positive",
                    int(row.get("positive_fold_count") or 0) == int(row.get("fold_count") or 0),
                    value=f"{row.get('positive_fold_count')}/{row.get('fold_count')}",
                    threshold="all",
                ),
                _gate(
                    f"{name}_min_return_floor",
                    _float(row.get("min_return_pct")) >= stress_min_return_pct,
                    value=_pct(_float(row.get("min_return_pct"))),
                    threshold=f">={stress_min_return_pct}",
                ),
                _gate(
                    f"{name}_actionable_drawdown_proxy_cap",
                    actionable_dd <= stress_max_drawdown_proxy_pct,
                    value={
                        "actionable": _pct(actionable_dd),
                        "raw": _pct(raw_dd),
                        "protected_alpha_folds": protected_alpha_count,
                    },
                    threshold=f"<={stress_max_drawdown_proxy_pct}",
                ),
                _gate(
                    f"{name}_protected_alpha_raw_drawdown_proxy_review",
                    raw_dd <= stress_max_drawdown_proxy_pct or protected_alpha_count == 0,
                    value={
                        "raw": _pct(raw_dd),
                        "actionable": _pct(actionable_dd),
                        "protected_alpha_folds": protected_alpha_count,
                    },
                    threshold=f"raw<={stress_max_drawdown_proxy_pct} or no_protected_alpha_folds",
                    severity="warning",
                ),
            ]
        )

    evidence_gates = [
        _gate(
            "exact_rolling_30_60_90_day_equity_available",
            bool(exact_rolling.get("all_windows_available")),
            value={
                "missing_fold_count": len(exact_rolling.get("missing_folds") or []),
                "windows": {
                    name: dict(payload).get("fold_count_with_window")
                    for name, payload in dict(exact_rolling.get("windows") or {}).items()
                },
            },
            threshold="required_before_full_live",
        ),
        _gate(
            "kst_hour_realized_pnl_available",
            bool(kst_hour_pnl.get("available")),
            value={
                "missing_fold_count": len(kst_hour_pnl.get("missing_folds") or []),
                "active_hours": len(kst_hour_pnl.get("realized_pnl_usd_units_by_kst_hour") or {}),
            },
            threshold="required_before_full_live",
        ),
        _gate(
            "live_or_paper_execution_parity_available",
            bool(execution_parity.get("passed")),
            value=execution_parity,
            threshold="passed execution parity report required before live",
        ),
    ]

    all_gates = oos_gates + calendar_gates + stress_gates + evidence_gates
    blockers = [gate["name"] for gate in all_gates if not gate["passed"] and gate["severity"] == "blocker"]
    warnings = [gate["name"] for gate in all_gates if not gate["passed"] and gate["severity"] == "warning"]
    paper_blockers = [
        gate["name"]
        for gate in oos_gates
        if not gate["passed"] and gate["severity"] == "blocker"
    ]
    tiny_canary_soft_blocker_exemptions: list[dict[str, Any]] = []

    def is_soft_tail_cost_floor(gate: dict[str, Any]) -> bool:
        if gate.get("name") != "cost_x3_funding3_min_return_floor":
            return False
        tail = dict(stress.get("cost_x3_funding3") or {})
        anchor = dict(stress.get("cost_x2_funding3") or {})
        tail_all_positive = int(tail.get("positive_fold_count") or 0) == int(tail.get("fold_count") or 0)
        anchor_all_positive = int(anchor.get("positive_fold_count") or 0) == int(anchor.get("fold_count") or 0)
        tail_actionable_dd = _float(
            tail.get("max_actionable_drawdown_proxy_pct"),
            _float(tail.get("max_drawdown_proxy_pct")),
        )
        anchor_actionable_dd = _float(
            anchor.get("max_actionable_drawdown_proxy_pct"),
            _float(anchor.get("max_drawdown_proxy_pct")),
        )
        return (
            bool(tail)
            and bool(anchor)
            and tail_all_positive
            and anchor_all_positive
            and _float(tail.get("min_return_pct")) > 0.0
            and _float(anchor.get("min_return_pct")) >= stress_min_return_pct
            and tail_actionable_dd <= stress_max_drawdown_proxy_pct
            and anchor_actionable_dd <= stress_max_drawdown_proxy_pct
        )

    tiny_canary_blockers: list[str] = []
    for gate in all_gates:
        if gate.get("passed") or gate.get("severity") != "blocker":
            continue
        if is_soft_tail_cost_floor(gate):
            tiny_canary_soft_blocker_exemptions.append(
                {
                    "name": gate.get("name"),
                    "reason": (
                        "x3 cost/funding floor is positive but below the full-live buffer; "
                        "x2 stress passes and x3 actionable drawdown remains within the canary cap."
                    ),
                    "value": gate.get("value"),
                    "threshold": gate.get("threshold"),
                }
            )
            continue
        tiny_canary_blockers.append(str(gate.get("name")))
    stress_dd_values = [
        _float(row.get("max_drawdown_proxy_pct"))
        for name, row in stress.items()
        if name != "baseline" and _float(row.get("max_drawdown_proxy_pct")) > 0.0
    ]
    actionable_stress_dd_values = [
        _float(row.get("max_actionable_drawdown_proxy_pct"))
        for name, row in stress.items()
        if name != "baseline" and _float(row.get("max_actionable_drawdown_proxy_pct")) > 0.0
    ]
    worst_stress_dd = max(stress_dd_values, default=0.0)
    worst_actionable_stress_dd = max(actionable_stress_dd_values, default=0.0)
    canary_size_multiplier = (
        min(1.0, canary_drawdown_proxy_pct / worst_stress_dd)
        if worst_stress_dd > 0.0
        else 1.0
    )
    baseline_leverage = max(
        (
            _float(
                dict(dict(fold.get("test_result") or {}).get("config") or {}).get(
                    "unit_account_exposure"
                ),
                _float(dict(fold.get("test_result") or {}).get("max_abs_account_exposure")),
            )
            for fold in walk_report.get("folds") or []
        ),
        default=0.0,
    )
    recommended_leverage_cap = baseline_leverage * canary_size_multiplier if baseline_leverage > 0 else None
    ready_for_full_live = not blockers and not warnings
    ready_for_paper = not paper_blockers
    ready_for_tiny_canary = ready_for_paper and not tiny_canary_blockers and canary_size_multiplier <= 0.35
    if ready_for_full_live:
        stage = "full_live_ready"
    elif ready_for_tiny_canary:
        stage = "tiny_canary_only"
    elif ready_for_paper:
        stage = "paper_only"
    else:
        stage = "research_only"
    remediation_plan = _build_remediation_plan(
        blockers=blockers,
        warnings=warnings,
        stress=stress,
        execution_parity=execution_parity,
    )

    return {
        "created_at": datetime.now(UTC).isoformat(),
        "input_walk_forward_report": input_walk_report,
        "input_stress_report": input_stress_report,
        "input_execution_parity_report": input_execution_parity_report,
        "symbol": walk_report.get("symbol"),
        "exec_interval": walk_report.get("exec_interval"),
        "stage": stage,
        "ready_for_full_live": ready_for_full_live,
        "ready_for_paper": ready_for_paper,
        "ready_for_tiny_canary": ready_for_tiny_canary,
        "blockers": blockers,
        "warnings": warnings,
        "stage_blockers": {
            "paper": paper_blockers,
            "tiny_canary": tiny_canary_blockers,
            "full_live": blockers,
        },
        "tiny_canary_soft_blocker_exemptions": tiny_canary_soft_blocker_exemptions,
        "deployment_limits": {
            "baseline_unit_account_exposure": _pct(baseline_leverage),
            "worst_stress_drawdown_proxy_pct": _pct(worst_stress_dd),
            "worst_actionable_stress_drawdown_proxy_pct": _pct(worst_actionable_stress_dd),
            "canary_drawdown_proxy_target_pct": _pct(canary_drawdown_proxy_pct),
            "recommended_max_size_multiplier": round(canary_size_multiplier, 4),
            "recommended_effective_leverage_cap": (
                _pct(recommended_leverage_cap) if recommended_leverage_cap is not None else None
            ),
        },
        "summary": {
            "fold_count": len(folds),
            "compounded_oos_return_pct": _pct(_float(aggregate.get("compounded_oos_return_pct"))),
            "avg_oos_return_pct": _pct(_float(aggregate.get("avg_oos_return_pct"))),
            "min_oos_return_pct": _pct(min(fold_returns, default=0.0)),
            "max_oos_drawdown_pct": _pct(max(fold_drawdowns, default=0.0)),
            "month_count": len(monthly),
            "losing_month_count": len(losing_months),
            "worst_month": worst_month,
            "worst_rolling_3m": worst_rolling_3m,
            "worst_rolling_6m": worst_rolling_6m,
            "worst_exact_rolling": exact_rolling.get("windows"),
        },
        "gates": {
            "oos": oos_gates,
            "calendar": calendar_gates,
            "stress": stress_gates,
            "evidence": evidence_gates,
        },
        "folds": folds,
        "monthly_returns": monthly,
        "rolling_3m_returns": rolling_3m,
        "rolling_6m_returns": rolling_6m,
        "exact_rolling": exact_rolling,
        "kst_hour_structure": kst_hours,
        "kst_hour_realized_pnl": kst_hour_pnl,
        "execution_parity": execution_parity,
        "stress_scenarios": stress,
        "remediation_plan": remediation_plan,
        "notes": [
            "Full-live requires passing historical, stressed-cost, and evidence availability gates.",
            "The canary size cap is derived from the worst stressed drawdown proxy and should not be treated as a profit target.",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary") or {})
    limits = dict(report.get("deployment_limits") or {})
    stage_blockers = dict(report.get("stage_blockers") or {})
    execution_parity = dict(report.get("execution_parity") or {})
    lines = [
        "# Market State Rotation V6 Live Readiness",
        "",
        f"- Stage: `{report.get('stage')}`",
        f"- Ready for full live: `{report.get('ready_for_full_live')}`",
        f"- Ready for paper: `{report.get('ready_for_paper')}`",
        f"- Ready for tiny canary: `{report.get('ready_for_tiny_canary')}`",
        f"- Blockers: `{', '.join(report.get('blockers') or [])}`",
        f"- Warnings: `{', '.join(report.get('warnings') or [])}`",
        f"- Paper blockers: `{', '.join(stage_blockers.get('paper') or [])}`",
        f"- Tiny canary blockers: `{', '.join(stage_blockers.get('tiny_canary') or [])}`",
        f"- Full live blockers: `{', '.join(stage_blockers.get('full_live') or [])}`",
        "",
        "## Summary",
        "",
        f"- Folds: `{summary.get('fold_count')}`",
        f"- Compounded OOS return %: `{summary.get('compounded_oos_return_pct')}`",
        f"- Min OOS return %: `{summary.get('min_oos_return_pct')}`",
        f"- Max OOS drawdown %: `{summary.get('max_oos_drawdown_pct')}`",
        f"- Months / losing months: `{summary.get('month_count')}/{summary.get('losing_month_count')}`",
        f"- Worst month: `{json.dumps(summary.get('worst_month'), ensure_ascii=False)}`",
        f"- Worst 3m rolling: `{json.dumps(summary.get('worst_rolling_3m'), ensure_ascii=False)}`",
        f"- Worst 6m rolling: `{json.dumps(summary.get('worst_rolling_6m'), ensure_ascii=False)}`",
        f"- Worst exact 30/60/90d rolling: `{json.dumps(summary.get('worst_exact_rolling'), ensure_ascii=False)}`",
        f"- Execution parity: `{json.dumps(execution_parity, ensure_ascii=False)}`",
        "",
        "## Deployment Limits",
        "",
        f"- Baseline unit account exposure: `{limits.get('baseline_unit_account_exposure')}`",
        f"- Worst stress DD proxy %: `{limits.get('worst_stress_drawdown_proxy_pct')}`",
        f"- Worst actionable stress DD proxy %: `{limits.get('worst_actionable_stress_drawdown_proxy_pct')}`",
        f"- Recommended max size multiplier: `{limits.get('recommended_max_size_multiplier')}`",
        f"- Recommended effective leverage cap: `{limits.get('recommended_effective_leverage_cap')}`",
        "",
        "## Failed Gates",
        "",
    ]
    failed = [
        gate
        for section in dict(report.get("gates") or {}).values()
        for gate in section
        if not gate.get("passed")
    ]
    if not failed:
        lines.append("- none")
    else:
        for gate in failed:
            lines.append(
                f"- `{gate.get('name')}`: value=`{gate.get('value')}`, threshold=`{gate.get('threshold')}`, severity=`{gate.get('severity')}`"
            )
    lines.extend(["", "## Tiny Canary Soft Exemptions", ""])
    soft_exemptions = list(report.get("tiny_canary_soft_blocker_exemptions") or [])
    if not soft_exemptions:
        lines.append("- none")
    else:
        for item in soft_exemptions:
            lines.append(
                f"- `{item.get('name')}`: value=`{item.get('value')}`, threshold=`{item.get('threshold')}`, reason=`{item.get('reason')}`"
            )
    lines.extend(["", "## Stress Scenarios", ""])
    lines.append("| Scenario | Min % | Max DD proxy % | Actionable DD proxy % | Protected alpha folds | Positive | Verdict |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for name, row in dict(report.get("stress_scenarios") or {}).items():
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(_pct(_float(row.get("min_return_pct")))),
                    str(_pct(_float(row.get("max_drawdown_proxy_pct")))),
                    str(_pct(_float(row.get("max_actionable_drawdown_proxy_pct")))),
                    str(row.get("protected_alpha_fold_count")),
                    f"{row.get('positive_fold_count')}/{row.get('fold_count')}",
                    str(row.get("verdict")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Remediation Plan", ""])
    remediation_plan = list(report.get("remediation_plan") or [])
    if not remediation_plan:
        lines.append("- none")
    else:
        for item in remediation_plan:
            lines.append(
                f"- `{item.get('blocker')}`: status=`{item.get('status')}`, next=`{item.get('next_action')}`"
            )
            priority_folds = list(item.get("priority_folds") or [])
            for fold in priority_folds[:3]:
                lines.append(
                    "  - "
                    f"fold `{fold.get('fold')}` return=`{fold.get('stressed_return_pct')}` "
                    f"gap=`{fold.get('stress_floor_gap_pct')}` "
                    f"cost_cut=`{fold.get('baseline_cost_reduction_needed_pct')}` "
                    f"causes=`{', '.join(fold.get('root_causes') or [])}`"
                )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build market-state rotation v6 live readiness report.")
    parser.add_argument("--walk-forward-report", required=True)
    parser.add_argument("--stress-report", required=True)
    parser.add_argument("--execution-parity-report", default="")
    parser.add_argument(
        "--report-dir",
        default="reports/validation/diagnostics/market_state_rotation_v6_live_readiness",
    )
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    walk_path = Path(args.walk_forward_report)
    stress_path = Path(args.stress_report)
    if not walk_path.is_absolute():
        walk_path = ROOT_DIR / walk_path
    if not stress_path.is_absolute():
        stress_path = ROOT_DIR / stress_path
    parity_path = Path(args.execution_parity_report) if args.execution_parity_report else None
    if parity_path is not None and not parity_path.is_absolute():
        parity_path = ROOT_DIR / parity_path
    walk_report = json.loads(walk_path.read_text())
    stress_report = json.loads(stress_path.read_text())
    execution_parity_report = json.loads(parity_path.read_text()) if parity_path is not None else None
    report = build_readiness_report(
        walk_report,
        stress_report,
        execution_parity_report=execution_parity_report,
        input_walk_report=str(walk_path.relative_to(ROOT_DIR)) if walk_path.is_relative_to(ROOT_DIR) else str(walk_path),
        input_stress_report=str(stress_path.relative_to(ROOT_DIR)) if stress_path.is_relative_to(ROOT_DIR) else str(stress_path),
        input_execution_parity_report=(
            str(parity_path.relative_to(ROOT_DIR))
            if parity_path is not None and parity_path.is_relative_to(ROOT_DIR)
            else (str(parity_path) if parity_path is not None else None)
        ),
    )
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_live_readiness.json"
        md_path = report_dir / "market_state_rotation_v6_live_readiness.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        md_path.write_text(_markdown(report))
        print(f"wrote {json_path.relative_to(ROOT_DIR)}")
        print(f"wrote {md_path.relative_to(ROOT_DIR)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
