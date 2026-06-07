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


def build_meta_router_shadow_wfo_compare(
    *,
    source_report: dict[str, Any],
    candidate_reports: list[tuple[str, dict[str, Any], str]],
    input_source_report: str | None = None,
    shadow_wfo_root: str | None = None,
    min_formal_folds: int = 12,
    max_return_giveback_pct: float = 3.0,
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
        lineage = _lineage_status(report)
        lineage_policy = _lineage_policy(recipe_id)
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
                "decision": decision,
                "decision_reasons": reasons,
                "next_actions": next_actions,
                "lineage_policy": lineage_policy,
                "lineage": lineage,
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
        ),
    )
    best_candidate = ranked[0] if ranked else None
    best_decision = str(dict(best_candidate or {}).get("decision") or "")
    next_action = (
        "Feed the formal non-regressing candidate into live readiness and paper parity gates."
        if best_decision == "promotion_candidate_after_formal_wfo"
        else "Run the best non-regressing candidate as formal WFO, or retune recipes when all candidates give back return."
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
            "max_drawdown_increase_pct": float(max_drawdown_increase_pct),
            "max_cost_increase_pct": float(max_cost_increase_pct),
        },
        "candidates": ranked,
        "best_candidate": best_candidate,
        "next_action": next_action,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Meta-Router Shadow WFO Compare",
        "",
        f"- status: `{report.get('status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- candidate_count: `{report.get('candidate_count')}`",
        "",
        "## Candidates",
        "",
    ]
    for item in list(report.get("candidates") or []):
        candidate = dict(item.get("candidate") or {})
        lines.append(
            f"- `{item.get('recipe_id')}`: decision=`{item.get('decision')}`, "
            f"return_delta=`{candidate.get('return_delta_vs_baseline_pct')}`, "
            f"dd_delta=`{candidate.get('drawdown_delta_vs_baseline_pct')}`, "
            f"cost_delta=`{candidate.get('cost_delta_vs_baseline_pct')}`, "
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
