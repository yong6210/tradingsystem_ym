#!/usr/bin/env python3
"""Gate the adaptive meta-router candidate against readiness evidence.

This report is intentionally research/paper only. It links the formal shadow WFO
comparison to live-readiness output, but it never submits or enables live orders.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]

DEFAULT_COMPARE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_meta_router_shadow_wfo_compare/"
    "market_state_rotation_v6_meta_router_shadow_wfo_compare.json"
)
DEFAULT_READINESS_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_live_readiness_meta_router_one_way_trim_tax_light_formal/"
    "market_state_rotation_v6_live_readiness.json"
)
DEFAULT_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_meta_router_promotion_gate"


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


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _pct(value: Any) -> float:
    return round(_float(value), 4)


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


def _promotion_decision(
    *,
    candidate: dict[str, Any],
    readiness: dict[str, Any],
    readiness_alignment: dict[str, Any],
) -> tuple[str, list[str], list[str]]:
    candidate_decision = str(candidate.get("decision") or "")
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

    if not bool(readiness_alignment.get("passed")):
        return (
            "blocked_readiness_candidate_mismatch",
            list(readiness_alignment.get("blockers") or ["readiness_candidate_alignment_failed"]),
            ["rerun_live_readiness_for_the_current_best_candidate_report"],
        )

    if bool(readiness.get("ready_for_full_live")):
        return (
            "full_live_gate_passed_manual_approval_required",
            ["formal_wfo_and_readiness_passed"],
            ["keep_live_disabled_until_explicit_manual_launch_approval"],
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
            return (
                "paper_ready_pending_execution_parity",
                ["formal_wfo_passed", "paper_readiness_passed", parity_reason],
                ["collect_paper_execution_parity_rows_before_tiny_canary_or_full_live"],
            )
        return (
            "paper_ready_with_readiness_warnings",
            ["formal_wfo_passed", "paper_readiness_passed", "warnings_or_noncritical_blockers_present"],
            ["review_readiness_warnings_before_any_canary"],
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
    input_compare_report: str | None = None,
    input_readiness_report: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    candidate = dict(compare_report.get("best_candidate") or {})
    candidate_metrics = dict(candidate.get("candidate") or {})
    mode_summary = dict(candidate_metrics.get("router_mode_summary") or {})
    execution_parity = dict(readiness_report.get("execution_parity") or {})
    readiness_alignment = _readiness_candidate_alignment(
        candidate=candidate,
        readiness=readiness_report,
    )
    decision, reasons, next_actions = _promotion_decision(
        candidate=candidate,
        readiness=readiness_report,
        readiness_alignment=readiness_alignment,
    )
    readiness_blockers = list(readiness_report.get("blockers") or [])
    next_blocker = None
    alignment_blockers = list(readiness_alignment.get("blockers") or [])
    if alignment_blockers:
        next_blocker = str(alignment_blockers[0])
    else:
        next_blocker = _first_blocker(readiness_report)

    return {
        "generated_at": generated_at.isoformat(),
        "status": "meta_router_promotion_gate_complete",
        "no_live_order_sent": True,
        "input_compare_report": input_compare_report,
        "input_readiness_report": input_readiness_report,
        "safety_policy": {
            "research_or_paper_only": True,
            "live_orders_enabled": False,
            "manual_approval_required_before_any_live_or_canary": True,
        },
        "promotion_decision": decision,
        "decision_reasons": reasons,
        "next_actions": next_actions,
        "next_blocker": next_blocker,
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
    limits = dict(readiness.get("deployment_limits") or {})
    return "\n".join(
        [
            "# Market State Rotation V6 Meta-Router Promotion Gate",
            "",
            f"- status: `{report.get('status')}`",
            f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
            f"- promotion_decision: `{report.get('promotion_decision')}`",
            f"- next_blocker: `{report.get('next_blocker')}`",
            f"- candidate: `{candidate.get('recipe_id')}` / `{candidate.get('decision')}`",
            f"- readiness candidate alignment: `{alignment.get('passed')}`",
            f"- return/DD/cost: `{candidate.get('compounded_return_pct')}` / `{candidate.get('max_drawdown_pct')}` / `{candidate.get('avg_cost_drag_pct')}`",
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
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_meta_router_promotion_gate(
        compare_report=_load_json(args.compare_report),
        readiness_report=_load_json(args.readiness_report),
        input_compare_report=_display_path(args.compare_report),
        input_readiness_report=_display_path(args.readiness_report),
    )
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        assert report_dir is not None
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_meta_router_promotion_gate.json"
        md_path = report_dir / "market_state_rotation_v6_meta_router_promotion_gate.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
