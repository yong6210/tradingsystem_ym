#!/usr/bin/env python3
"""Audit conditional winner-refill candidates with a historical holdout proxy.

This is a research-only proxy. It can add evidence that a conditional overlay did
not damage held-out historical folds, but it does not replace real shadow
observation and never enables live orders.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]

DEFAULT_BASELINE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_imp490_current_top_candidate_audit/"
    "market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json"
)
DEFAULT_CANDIDATE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_meta_router_shadow_wfo/"
    "winner_refill_after_trim_100_r045_s5_no_riskoff_cond_minext075_cost30_60_overlay_anchor_formal/"
    "market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json"
)
DEFAULT_COMPARE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_meta_router_shadow_wfo_compare/"
    "market_state_rotation_v6_meta_router_shadow_wfo_compare.json"
)
DEFAULT_REPORT_DIR = (
    "reports/validation/diagnostics/market_state_rotation_v6_conditional_overfit_holdout_audit"
)


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: str | Path | None) -> str | None:
    resolved = _resolve(path)
    if resolved is None:
        return None
    try:
        return str(resolved.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(resolved)


def _read_json(path: str | Path) -> dict[str, Any]:
    resolved = _resolve(path)
    if resolved is None:
        raise ValueError("path is required")
    return dict(json.loads(resolved.read_text(encoding="utf-8")))


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _pct(value: Any) -> float:
    return round(_float(value), 4)


def _fold_map(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    folds: dict[int, dict[str, Any]] = {}
    for item in list(report.get("folds") or []):
        if not isinstance(item, dict):
            continue
        try:
            fold = int(item.get("fold"))
        except (TypeError, ValueError):
            continue
        folds[fold] = item
    return folds


def _fold_metrics(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item.get("test_result") or {})
    model_id = str(item.get("selected_model_id") or result.get("model_id") or "")
    overlays = list(item.get("after_selection_overlays_applied") or [])
    return {
        "fold": int(item.get("fold") or 0),
        "test_start": item.get("test_start") or item.get("test_start_at"),
        "test_end": item.get("test_end") or item.get("test_end_at"),
        "model_id": model_id,
        "total_return_pct": _pct(result.get("total_return_pct")),
        "max_drawdown_pct": _pct(result.get("max_drawdown_pct")),
        "estimated_cost_drag_pct": _pct(result.get("estimated_cost_drag_pct")),
        "trade_like_events": int(result.get("trade_like_events") or 0),
        "after_selection_overlays_applied": overlays,
    }


def _compound_return(fold_returns_pct: list[float]) -> float:
    equity = 1.0
    for value in fold_returns_pct:
        equity *= 1.0 + (_float(value) / 100.0)
    return round((equity - 1.0) * 100.0, 4)


def _aggregate(report: dict[str, Any]) -> dict[str, Any]:
    aggregate = dict(report.get("aggregate") or {})
    return {
        "fold_count": int(aggregate.get("fold_count") or 0),
        "compounded_return_pct": _pct(aggregate.get("compounded_oos_return_pct")),
        "avg_return_pct": _pct(aggregate.get("avg_oos_return_pct")),
        "min_return_pct": _pct(aggregate.get("min_oos_return_pct")),
        "positive_fold_count": int(aggregate.get("positive_fold_count") or 0),
        "max_drawdown_pct": _pct(aggregate.get("max_fold_drawdown_pct")),
        "avg_cost_drag_pct": _pct(aggregate.get("avg_oos_cost_drag_pct")),
        "trade_like_events": int(aggregate.get("total_trade_like_events") or 0),
    }


def _check(name: str, passed: bool, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": dict(detail or {})}


def build_conditional_overfit_holdout_audit(
    *,
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    compare_report: dict[str, Any] | None = None,
    baseline_report_path: str | None = None,
    candidate_report_path: str | None = None,
    compare_report_path: str | None = None,
    tail_holdout_folds: int = 4,
    concentration_warning_share: float = 0.60,
    concentration_block_share: float = 0.65,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    compare_report = dict(compare_report or {})
    best_candidate = dict(compare_report.get("best_candidate") or {})
    overfit_audit = dict(best_candidate.get("overfit_audit") or {})
    token = str(overfit_audit.get("conditional_model_token") or "wfWinPyrMinExtAS")

    baseline_folds = _fold_map(baseline_report)
    candidate_folds = _fold_map(candidate_report)
    common_folds = sorted(set(baseline_folds) & set(candidate_folds))
    deltas: list[dict[str, Any]] = []
    changed_folds: list[int] = []
    positive_delta_folds: list[int] = []
    negative_delta_folds: list[int] = []
    token_folds: list[int] = []

    for fold in common_folds:
        baseline = _fold_metrics(baseline_folds[fold])
        candidate = _fold_metrics(candidate_folds[fold])
        return_delta = round(candidate["total_return_pct"] - baseline["total_return_pct"], 4)
        dd_delta = round(candidate["max_drawdown_pct"] - baseline["max_drawdown_pct"], 4)
        cost_delta = round(
            candidate["estimated_cost_drag_pct"] - baseline["estimated_cost_drag_pct"], 4
        )
        event_delta = int(candidate["trade_like_events"] - baseline["trade_like_events"])
        token_applied = token in str(candidate.get("model_id") or "")
        if token_applied:
            token_folds.append(fold)
        changed = any(
            [
                abs(return_delta) > 1e-6,
                abs(dd_delta) > 1e-6,
                abs(cost_delta) > 1e-6,
                event_delta != 0,
            ]
        )
        if changed:
            changed_folds.append(fold)
        if return_delta > 1e-6:
            positive_delta_folds.append(fold)
        if return_delta < -1e-6:
            negative_delta_folds.append(fold)
        deltas.append(
            {
                "fold": fold,
                "test_start": candidate["test_start"],
                "test_end": candidate["test_end"],
                "return_delta_pct": return_delta,
                "drawdown_delta_pct": dd_delta,
                "cost_delta_pct": cost_delta,
                "trade_event_delta": event_delta,
                "conditional_token_applied": token_applied,
                "candidate_return_pct": candidate["total_return_pct"],
                "baseline_return_pct": baseline["total_return_pct"],
                "candidate_drawdown_pct": candidate["max_drawdown_pct"],
                "baseline_drawdown_pct": baseline["max_drawdown_pct"],
                "candidate_cost_drag_pct": candidate["estimated_cost_drag_pct"],
                "baseline_cost_drag_pct": baseline["estimated_cost_drag_pct"],
            }
        )

    tail_count = max(1, min(int(tail_holdout_folds or 1), len(common_folds)))
    tail_folds = common_folds[-tail_count:]
    tail_deltas = [item for item in deltas if int(item["fold"]) in set(tail_folds)]
    tail_candidate_return = _compound_return(
        [float(item["candidate_return_pct"]) for item in tail_deltas]
    )
    tail_baseline_return = _compound_return([float(item["baseline_return_pct"]) for item in tail_deltas])
    tail_return_delta = round(tail_candidate_return - tail_baseline_return, 4)
    tail_worse_folds = [
        int(item["fold"])
        for item in tail_deltas
        if _float(item["return_delta_pct"]) < -1e-6 or _float(item["drawdown_delta_pct"]) > 1e-6
    ]
    unchanged_folds = [item for item in deltas if int(item["fold"]) not in set(changed_folds)]
    unchanged_worse_folds = [
        int(item["fold"])
        for item in unchanged_folds
        if _float(item["return_delta_pct"]) < -1e-6 or _float(item["drawdown_delta_pct"]) > 1e-6
    ]
    token_worse_folds = [
        int(item["fold"])
        for item in deltas
        if item.get("conditional_token_applied")
        and (_float(item["return_delta_pct"]) < -1e-6 or _float(item["drawdown_delta_pct"]) > 1e-6)
    ]

    baseline_agg = _aggregate(baseline_report)
    candidate_agg = _aggregate(candidate_report)
    aggregate_return_delta = round(
        candidate_agg["compounded_return_pct"] - baseline_agg["compounded_return_pct"], 4
    )
    aggregate_dd_delta = round(candidate_agg["max_drawdown_pct"] - baseline_agg["max_drawdown_pct"], 4)
    aggregate_cost_delta = round(candidate_agg["avg_cost_drag_pct"] - baseline_agg["avg_cost_drag_pct"], 4)
    aggregate_event_delta = int(candidate_agg["trade_like_events"] - baseline_agg["trade_like_events"])
    top_positive_delta = max([_float(item["return_delta_pct"]) for item in deltas], default=0.0)
    positive_delta_sum = sum(max(0.0, _float(item["return_delta_pct"])) for item in deltas)
    top_positive_share = (
        round(top_positive_delta / positive_delta_sum, 4) if positive_delta_sum > 0.0 else 0.0
    )

    checks = [
        _check(
            "common_fold_coverage",
            len(common_folds) == baseline_agg["fold_count"] == candidate_agg["fold_count"],
            {
                "common_fold_count": len(common_folds),
                "baseline_fold_count": baseline_agg["fold_count"],
                "candidate_fold_count": candidate_agg["fold_count"],
            },
        ),
        _check(
            "aggregate_return_improved",
            aggregate_return_delta > 0.0,
            {"return_delta_pct": aggregate_return_delta},
        ),
        _check(
            "aggregate_drawdown_not_worse",
            aggregate_dd_delta <= 1e-6,
            {"drawdown_delta_pct": aggregate_dd_delta},
        ),
        _check(
            "all_candidate_folds_positive",
            candidate_agg["positive_fold_count"] == candidate_agg["fold_count"],
            {
                "positive_fold_count": candidate_agg["positive_fold_count"],
                "fold_count": candidate_agg["fold_count"],
            },
        ),
        _check(
            "tail_holdout_proxy_not_worse",
            tail_return_delta >= -1e-6 and not tail_worse_folds,
            {
                "tail_folds": tail_folds,
                "candidate_compounded_return_pct": tail_candidate_return,
                "baseline_compounded_return_pct": tail_baseline_return,
                "tail_return_delta_pct": tail_return_delta,
                "tail_worse_folds": tail_worse_folds,
            },
        ),
        _check(
            "unchanged_folds_not_damaged",
            not unchanged_worse_folds,
            {
                "unchanged_fold_count": len(unchanged_folds),
                "unchanged_worse_folds": unchanged_worse_folds,
            },
        ),
        _check(
            "conditional_token_folds_not_damaged",
            not token_worse_folds,
            {"conditional_token": token, "conditional_token_folds": token_folds, "worse_folds": token_worse_folds},
        ),
        _check(
            "positive_delta_concentration_below_block_threshold",
            top_positive_share <= float(concentration_block_share),
            {
                "top_positive_delta_share": top_positive_share,
                "block_threshold": float(concentration_block_share),
            },
        ),
    ]
    blockers = [item["name"] for item in checks if not bool(item.get("passed"))]
    warnings: list[str] = []
    if top_positive_share >= float(concentration_warning_share):
        warnings.append("positive_delta_is_still_concentrated_in_top_fold")
    if overfit_audit.get("status") == "requires_shadow_holdout_review":
        warnings.append("historical_proxy_does_not_replace_real_shadow_holdout")

    status = (
        "historical_proxy_pass_real_shadow_required"
        if not blockers
        else "historical_proxy_failed_real_shadow_required"
    )
    return {
        "generated_at": generated_at.isoformat(),
        "status": status,
        "schema_version": "market_state_rotation_v6_conditional_overfit_holdout_audit_v1",
        "baseline_report": baseline_report_path,
        "candidate_report": candidate_report_path,
        "compare_report": compare_report_path,
        "candidate_recipe_id": best_candidate.get("recipe_id"),
        "candidate_decision": best_candidate.get("decision"),
        "conditional_overlay_keys": list(overfit_audit.get("conditional_overlay_keys") or []),
        "conditional_model_token": token,
        "baseline_aggregate": baseline_agg,
        "candidate_aggregate": candidate_agg,
        "aggregate_delta": {
            "return_delta_pct": aggregate_return_delta,
            "drawdown_delta_pct": aggregate_dd_delta,
            "avg_cost_delta_pct": aggregate_cost_delta,
            "trade_event_delta": aggregate_event_delta,
        },
        "fold_delta_summary": {
            "common_fold_count": len(common_folds),
            "changed_fold_count": len(changed_folds),
            "changed_folds": changed_folds,
            "positive_delta_fold_count": len(positive_delta_folds),
            "positive_delta_folds": positive_delta_folds,
            "negative_delta_fold_count": len(negative_delta_folds),
            "negative_delta_folds": negative_delta_folds,
            "top_positive_delta_pct": round(top_positive_delta, 4),
            "positive_delta_sum_pct": round(positive_delta_sum, 4),
            "top_positive_delta_share": top_positive_share,
        },
        "tail_holdout_proxy": {
            "folds": tail_folds,
            "candidate_compounded_return_pct": tail_candidate_return,
            "baseline_compounded_return_pct": tail_baseline_return,
            "return_delta_pct": tail_return_delta,
            "worse_folds": tail_worse_folds,
            "passed": tail_return_delta >= -1e-6 and not tail_worse_folds,
        },
        "conditional_token_proxy": {
            "token": token,
            "folds": token_folds,
            "worse_folds": token_worse_folds,
            "passed": not token_worse_folds,
        },
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "limitations": [
            "uses_historical_wfo_archive_after_the_rule_was_known",
            "does_not_create_true_future_unseen_market_data",
            "must_not_clear_live_or_canary_promotion_without_real_shadow_or_operator_review",
        ],
        "fold_deltas": deltas,
        "next_action": (
            "keep_conditional_candidate_shadow_only_until_real_shadow_holdout_or_operator_review"
            if not blockers
            else "fix_or_reject_conditional_candidate_before_shadow_holdout_promotion"
        ),
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    aggregate_delta = dict(payload.get("aggregate_delta") or {})
    fold_delta = dict(payload.get("fold_delta_summary") or {})
    tail = dict(payload.get("tail_holdout_proxy") or {})
    token = dict(payload.get("conditional_token_proxy") or {})
    lines = [
        "# Market State Rotation V6 Conditional Overfit Holdout Audit",
        "",
        f"- status: `{payload.get('status')}`",
        f"- candidate_recipe_id: `{payload.get('candidate_recipe_id')}`",
        f"- aggregate_return_delta_pct: `{aggregate_delta.get('return_delta_pct')}`",
        f"- aggregate_drawdown_delta_pct: `{aggregate_delta.get('drawdown_delta_pct')}`",
        f"- aggregate_avg_cost_delta_pct: `{aggregate_delta.get('avg_cost_delta_pct')}`",
        f"- changed_folds: `{fold_delta.get('changed_folds')}`",
        f"- positive_delta_top_share: `{fold_delta.get('top_positive_delta_share')}`",
        f"- tail_holdout_proxy_folds: `{tail.get('folds')}`",
        f"- tail_holdout_proxy_return_delta_pct: `{tail.get('return_delta_pct')}`",
        f"- tail_holdout_proxy_passed: `{tail.get('passed')}`",
        f"- conditional_token_folds: `{token.get('folds')}`",
        f"- conditional_token_proxy_passed: `{token.get('passed')}`",
        f"- blockers: `{payload.get('blockers')}`",
        f"- warnings: `{payload.get('warnings')}`",
        f"- next_action: `{payload.get('next_action')}`",
        f"- no_live_order_sent: `{payload.get('no_live_order_sent')}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-report", default=DEFAULT_BASELINE_REPORT)
    parser.add_argument("--candidate-report", default=DEFAULT_CANDIDATE_REPORT)
    parser.add_argument("--compare-report", default=DEFAULT_COMPARE_REPORT)
    parser.add_argument("--tail-holdout-folds", type=int, default=4)
    parser.add_argument("--concentration-warning-share", type=float, default=0.60)
    parser.add_argument("--concentration-block-share", type=float, default=0.65)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    baseline_path = _resolve(args.baseline_report)
    candidate_path = _resolve(args.candidate_report)
    compare_path = _resolve(args.compare_report)
    if baseline_path is None or candidate_path is None or compare_path is None:
        raise SystemExit("baseline, candidate, and compare reports are required")
    payload = build_conditional_overfit_holdout_audit(
        baseline_report=_read_json(baseline_path),
        candidate_report=_read_json(candidate_path),
        compare_report=_read_json(compare_path),
        baseline_report_path=_display_path(baseline_path),
        candidate_report_path=_display_path(candidate_path),
        compare_report_path=_display_path(compare_path),
        tail_holdout_folds=int(args.tail_holdout_folds),
        concentration_warning_share=float(args.concentration_warning_share),
        concentration_block_share=float(args.concentration_block_share),
    )
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        if report_dir is None:
            raise SystemExit("report-dir is required")
        report_dir.mkdir(parents=True, exist_ok=True)
        latest = report_dir / "market_state_rotation_v6_conditional_overfit_holdout_audit.json"
        latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stamped = report_dir / (
            "market_state_rotation_v6_conditional_overfit_holdout_audit_"
            f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        stamped.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _write_markdown(report_dir / "market_state_rotation_v6_conditional_overfit_holdout_audit.md", payload)
        payload["report_path"] = _display_path(latest)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
