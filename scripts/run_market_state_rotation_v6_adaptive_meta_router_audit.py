#!/usr/bin/env python3
"""Audit the adaptive meta-router plan for market-state rotation v6.

This is a research/paper-only governance layer. It turns the WeDom-style
"change strategy by market state" idea into explicit playbook contracts and
checks whether the current v6 evidence is ready for those contracts. It never
submits live orders and does not enable live trading.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]

DEFAULT_LIVE_READINESS_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_live_readiness_current/"
    "market_state_rotation_v6_live_readiness.json"
)
DEFAULT_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_adaptive_meta_router_audit"


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


def _load_json_optional(path: str | Path | None) -> dict[str, Any] | None:
    resolved = _resolve(path)
    if resolved is None or not resolved.exists():
        return None
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


def _counter_merge(target: dict[str, int], payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    for key, value in payload.items():
        target[str(key)] = target.get(str(key), 0) + int(value or 0)


def _playbook_contracts() -> list[dict[str, Any]]:
    return [
        {
            "mode": "trend_reaction",
            "objective": "follow confirmed higher-timeframe bias while buying/selling reactions, not chop.",
            "allowed_modules": ["base_entry", "chase_entry", "winner_only_capacity_extension"],
            "blocked_modules": ["range_broad_base_unlock", "counter_trend_full_flip_without_invalidation"],
            "sizing_policy": {
                "base": "normal_or_reduced_by_context",
                "chase": "allowed_when_extension_and_score_stack_pass",
                "probe": "optional_only_when_signal_cadence_is_sparse",
            },
            "promotion_gate": "positive trend_reaction mode return with drawdown inside readiness cap.",
        },
        {
            "mode": "one_way_chase",
            "objective": "keep the runner alive in one-way markets and avoid repeated taxed trims.",
            "allowed_modules": ["one_way_runner_protection", "with_trend_chase", "delayed_trim"],
            "blocked_modules": ["counter_trend_base", "unconditional_reversal", "forced_trim_without_thesis_break"],
            "sizing_policy": {
                "with_trend": "normal_or_slightly_expanded_after_validation",
                "against_trend": "zero_or_dust_until_exhaustion_contract_passes",
            },
            "promotion_gate": "forced-trim cost falls without increasing max drawdown or liquidation risk.",
        },
        {
            "mode": "exhaustion_reversal",
            "objective": "switch only after one-way continuation fails and opposite evidence dominates.",
            "allowed_modules": ["scenario_flip", "one_way_reversal_switch", "small_reversal_probe"],
            "blocked_modules": ["full_size_first_reversal", "score_only_flip"],
            "sizing_policy": {
                "first_reversal": "small",
                "scale": "only_after_follow_through_or_failed_reclaim_retest",
            },
            "promotion_gate": "reversal mode has non-negative OOS return and no drawdown expansion.",
        },
        {
            "mode": "range_transition",
            "objective": "avoid forcing trend trades inside ambiguous ranges.",
            "allowed_modules": ["quality_gated_near_miss_micro_probe", "wyckoff_like_structure_classifier"],
            "blocked_modules": ["broad_MC04_relaxation", "large_base_or_chase_entry"],
            "sizing_policy": {
                "base": "blocked_or_heavily_reduced",
                "probe": "quality_gated_only",
                "chase": "blocked_until_breakout_confirmation",
            },
            "promotion_gate": "range probes improve cadence without creating probe alpha leak.",
        },
        {
            "mode": "risk_off",
            "objective": "protect equity when execution, drawdown, or data quality is degraded.",
            "allowed_modules": ["inventory_trim", "cooldown", "paper_only_observation"],
            "blocked_modules": ["new_large_entries", "leverage_expansion", "live_promotion"],
            "sizing_policy": {
                "new_entry": "zero_or_dust",
                "inventory": "trim_or_flatten_by_risk_state",
            },
            "promotion_gate": "risk-off exits reduce tail drawdown without blocking all profitable recovery.",
        },
    ]


def _readiness_summary(live_readiness_report: dict[str, Any] | None) -> dict[str, Any]:
    if not live_readiness_report:
        return {
            "available": False,
            "stage": "unknown",
            "blockers": [],
            "warnings": [],
            "upgrade_backlog_ids": [],
        }
    summary = dict(live_readiness_report.get("summary") or {})
    backlog = list(dict(live_readiness_report.get("upgrade_backlog") or {}).get("items") or [])
    return {
        "available": True,
        "stage": live_readiness_report.get("stage"),
        "ready_for_paper": bool(live_readiness_report.get("ready_for_paper")),
        "ready_for_tiny_canary": bool(live_readiness_report.get("ready_for_tiny_canary")),
        "ready_for_full_live": bool(live_readiness_report.get("ready_for_full_live")),
        "blockers": list(live_readiness_report.get("blockers") or []),
        "warnings": list(live_readiness_report.get("warnings") or []),
        "compounded_oos_return_pct": _pct(summary.get("compounded_oos_return_pct")),
        "max_oos_drawdown_pct": _pct(summary.get("max_oos_drawdown_pct")),
        "worst_exact_30d_return_pct": _pct(
            dict(dict(summary.get("worst_exact_rolling") or {}).get("30d") or {}).get(
                "worst_min_return_pct"
            )
        ),
        "upgrade_backlog_ids": [str(item.get("id")) for item in backlog],
    }


def _walk_forward_path_from_readiness(live_readiness_report: dict[str, Any] | None) -> str | None:
    if not live_readiness_report:
        return None
    value = live_readiness_report.get("input_walk_forward_report")
    return str(value) if value else None


def _router_mode_summary(walk_report: dict[str, Any] | None) -> dict[str, Any]:
    if not walk_report:
        return {
            "available": False,
            "router_enabled_in_any_fold": False,
            "active_modes": [],
            "modes": {},
            "add_by_router_mode": {},
            "remove_by_router_mode": {},
        }

    modes: dict[str, dict[str, Any]] = {}
    add_by_router_mode: dict[str, int] = {}
    remove_by_router_mode: dict[str, int] = {}
    router_enabled = False
    fold_count = 0

    for fold in list(walk_report.get("folds") or []):
        result = dict(fold.get("test_result") or {})
        config = dict(result.get("config") or {})
        router_enabled = router_enabled or bool(config.get("regime_router_enabled"))
        diagnostics = dict(result.get("event_diagnostics") or {})
        _counter_merge(add_by_router_mode, diagnostics.get("add_by_router_mode"))
        _counter_merge(remove_by_router_mode, diagnostics.get("remove_by_router_mode"))
        performance = dict(result.get("router_mode_performance") or {})
        if performance:
            fold_count += 1
        for mode, payload_raw in performance.items():
            payload = dict(payload_raw or {})
            row = modes.setdefault(
                str(mode),
                {
                    "fold_count": 0,
                    "positive_fold_count": 0,
                    "bars": 0,
                    "exposed_bars": 0,
                    "add_events": 0,
                    "remove_events": 0,
                    "equity_multiple": 1.0,
                    "min_return_pct": None,
                    "max_return_pct": None,
                    "max_drawdown_pct": 0.0,
                    "side_bars": {},
                },
            )
            ret = _float(payload.get("return_pct"))
            row["fold_count"] = int(row["fold_count"]) + 1
            row["positive_fold_count"] = int(row["positive_fold_count"]) + (1 if ret > 0.0 else 0)
            row["bars"] = int(row["bars"]) + int(payload.get("bars") or 0)
            row["exposed_bars"] = int(row["exposed_bars"]) + int(payload.get("exposed_bars") or 0)
            row["add_events"] = int(row["add_events"]) + int(payload.get("add_events") or 0)
            row["remove_events"] = int(row["remove_events"]) + int(payload.get("remove_events") or 0)
            row["equity_multiple"] = float(row["equity_multiple"]) * max(1.0 + ret / 100.0, 1e-12)
            row["min_return_pct"] = ret if row["min_return_pct"] is None else min(float(row["min_return_pct"]), ret)
            row["max_return_pct"] = ret if row["max_return_pct"] is None else max(float(row["max_return_pct"]), ret)
            row["max_drawdown_pct"] = max(_float(row["max_drawdown_pct"]), _float(payload.get("max_drawdown_pct")))
            side_bars = dict(row.get("side_bars") or {})
            for side, count in dict(payload.get("side_bars") or {}).items():
                side_bars[str(side)] = side_bars.get(str(side), 0) + int(count or 0)
            row["side_bars"] = side_bars

    compact_modes: dict[str, dict[str, Any]] = {}
    for mode, row in sorted(modes.items()):
        bars = max(int(row.get("bars") or 0), 1)
        exposed = int(row.get("exposed_bars") or 0)
        equity_multiple = _float(row.get("equity_multiple"), 1.0)
        compact_modes[mode] = {
            "fold_count": int(row.get("fold_count") or 0),
            "positive_fold_count": int(row.get("positive_fold_count") or 0),
            "compounded_return_pct": _pct((equity_multiple - 1.0) * 100.0),
            "min_return_pct": _pct(row.get("min_return_pct")),
            "max_return_pct": _pct(row.get("max_return_pct")),
            "max_drawdown_pct": _pct(row.get("max_drawdown_pct")),
            "bars": int(row.get("bars") or 0),
            "exposed_bars": exposed,
            "exposure_share": round(exposed / bars, 6),
            "add_events": int(row.get("add_events") or 0),
            "remove_events": int(row.get("remove_events") or 0),
            "side_bars": dict(sorted(dict(row.get("side_bars") or {}).items())),
        }

    active_modes = [mode for mode, row in compact_modes.items() if int(row.get("bars") or 0) > 0]
    only_legacy = set(active_modes).issubset({"legacy"})
    if not router_enabled and not only_legacy:
        router_enabled = True
    return {
        "available": True,
        "fold_count_with_router_performance": fold_count,
        "router_enabled_in_any_fold": bool(router_enabled),
        "router_contract_active": bool(router_enabled and not only_legacy),
        "active_modes": active_modes,
        "modes": compact_modes,
        "add_by_router_mode": dict(sorted(add_by_router_mode.items())),
        "remove_by_router_mode": dict(sorted(remove_by_router_mode.items())),
    }


def _aggregate_context_summary(walk_report: dict[str, Any] | None) -> dict[str, Any]:
    if not walk_report:
        return {"available": False}
    aggregate = dict(walk_report.get("aggregate") or {})
    add_by_role = dict(aggregate.get("test_add_by_role_counts") or {})
    add_by_role_share = dict(aggregate.get("test_add_by_role_share") or {})
    cost = dict(aggregate.get("test_cost_attribution") or {})
    by_reason_cost = dict(cost.get("by_reason_pct") or {})
    diagnostics = dict(aggregate.get("test_add_distribution_diagnostics") or {})
    return {
        "available": True,
        "fold_count": int(aggregate.get("fold_count") or 0),
        "compounded_oos_return_pct": _pct(aggregate.get("compounded_oos_return_pct")),
        "min_oos_return_pct": _pct(aggregate.get("min_oos_return_pct")),
        "max_fold_drawdown_pct": _pct(aggregate.get("max_fold_drawdown_pct")),
        "avg_oos_cost_drag_pct": _pct(aggregate.get("avg_oos_cost_drag_pct")),
        "max_oos_cost_drag_pct": _pct(aggregate.get("max_oos_cost_drag_pct")),
        "total_trade_like_events": int(aggregate.get("total_trade_like_events") or 0),
        "add_by_role": add_by_role,
        "add_by_role_share": add_by_role_share,
        "dominant_add_role": diagnostics.get("dominant_add_role"),
        "dominant_add_role_share": _float(diagnostics.get("dominant_add_role_share")),
        "one_way_forced_trim_cost_pct": _pct(by_reason_cost.get("one_way_against_forced_trim")),
        "reaction_trim_cost_pct": _pct(by_reason_cost.get("v6_reaction_inventory_trim")),
        "hard_time_exit_cost_pct": _pct(by_reason_cost.get("hard_intraday_time_exit")),
        "base_entry_cost_pct": _pct(by_reason_cost.get("base_entry")),
        "risk_tag_counts": dict(
            dict(aggregate.get("selected_reaction_usd_performance") or {})
            .get("200.0", {})
            .get("risk_tag_counts")
            or {}
        ),
    }


def _gap_items(
    *,
    readiness: dict[str, Any],
    router: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    backlog_ids = set(readiness.get("upgrade_backlog_ids") or [])
    blockers = set(readiness.get("blockers") or [])
    warnings = set(readiness.get("warnings") or [])

    if not router.get("router_contract_active"):
        gaps.append(
            {
                "id": "router_contract_not_active_in_current_top_candidate",
                "severity": "high",
                "type": "strategy_architecture",
                "evidence": {
                    "router_enabled_in_any_fold": bool(router.get("router_enabled_in_any_fold")),
                    "active_modes": list(router.get("active_modes") or []),
                },
                "next_action": (
                    "Run the current top candidate through explicit regime-router WFO candidates before "
                    "treating the system as market-adaptive."
                ),
            }
        )

    weak_modes = [
        mode
        for mode, row in dict(router.get("modes") or {}).items()
        if mode != "legacy" and _float(row.get("min_return_pct")) < 0.0
    ]
    if weak_modes:
        gaps.append(
            {
                "id": "negative_router_mode_pockets",
                "severity": "high",
                "type": "router_mode_quality",
                "evidence": {"negative_min_return_modes": weak_modes},
                "next_action": "Add mode-specific abstain, trim, or reduced-size rules before widening that mode.",
            }
        )

    if "live_or_paper_execution_parity_available" in blockers:
        gaps.append(
            {
                "id": "paper_execution_parity_missing",
                "severity": "critical",
                "type": "deployment_evidence",
                "evidence": {"stage": readiness.get("stage"), "blocker_present": True},
                "next_action": "Collect paper apply rows before tiny canary or full live promotion.",
            }
        )

    if "base_negative_context_pruning" in backlog_ids or _float(context.get("dominant_add_role_share")) >= 0.55:
        gaps.append(
            {
                "id": "base_context_pruning_needed",
                "severity": "high",
                "type": "alpha_leak_or_role_concentration",
                "evidence": {
                    "dominant_add_role": context.get("dominant_add_role"),
                    "dominant_add_role_share": _pct(context.get("dominant_add_role_share")),
                    "base_add_share": _pct(dict(context.get("add_by_role_share") or {}).get("base")),
                },
                "next_action": "Test context-specific base suppression instead of cutting all base entries.",
            }
        )

    if (
        "one_way_forced_trim_cost_repair" in backlog_ids
        or _float(context.get("one_way_forced_trim_cost_pct")) >= 4.0
    ):
        gaps.append(
            {
                "id": "one_way_runner_protection_needed",
                "severity": "high",
                "type": "trend_runner_tax",
                "evidence": {
                    "one_way_forced_trim_cost_pct": _pct(context.get("one_way_forced_trim_cost_pct")),
                    "reaction_trim_cost_pct": _pct(context.get("reaction_trim_cost_pct")),
                },
                "next_action": (
                    "Separate one-way continuation hold rules from choppy reversal trims; retest drawdown and cost."
                ),
            }
        )

    if "single_unit_capacity_review" in backlog_ids:
        gaps.append(
            {
                "id": "winner_only_capacity_ablation_needed",
                "severity": "medium",
                "type": "capacity",
                "evidence": {"backlog_present": True},
                "next_action": "Allow added unit tiers only after unrealized profit or thesis validation, not at entry.",
            }
        )

    if "probe_alpha_leak_pruning" in backlog_ids:
        gaps.append(
            {
                "id": "probe_alpha_leak_pruning_needed",
                "severity": "high",
                "type": "entry_quality",
                "evidence": {"backlog_present": True},
                "next_action": "Prune losing probe contexts before broadening near-miss probes.",
            }
        )

    if {"all_exact_30d_windows_positive", "all_exact_60d_windows_positive"} & warnings:
        gaps.append(
            {
                "id": "short_window_tail_still_needs_review",
                "severity": "medium",
                "type": "calendar_tail",
                "evidence": {
                    "worst_exact_30d_return_pct": readiness.get("worst_exact_30d_return_pct"),
                    "warnings": sorted({"all_exact_30d_windows_positive", "all_exact_60d_windows_positive"} & warnings),
                },
                "next_action": "Keep exact 30/60d tail review in research gates; do not treat high CAGR as stability.",
            }
        )

    return gaps


def _experiment_order(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gap_ids = {str(item.get("id")) for item in gaps}
    order = [
        {
            "id": "router_contract_shadow_wfo",
            "enabled": "router_contract_not_active_in_current_top_candidate" in gap_ids,
            "goal": "turn implicit v6 behavior into explicit regime-router WFO candidates.",
            "must_not_do": "do_not_promote_to_live_from_this_audit",
        },
        {
            "id": "one_way_runner_protection_ablation",
            "enabled": "one_way_runner_protection_needed" in gap_ids,
            "goal": "reduce one-way forced-trim tax while preserving invalidation exits.",
            "must_not_do": "unconditional_hold_or_unconditional_flip",
        },
        {
            "id": "negative_base_context_pruning_ablation",
            "enabled": "base_context_pruning_needed" in gap_ids,
            "goal": "remove only negative base pockets and preserve positive base/chase contributions.",
            "must_not_do": "blanket_base_entry_cut",
        },
        {
            "id": "probe_alpha_leak_pruning_ablation",
            "enabled": "probe_alpha_leak_pruning_needed" in gap_ids,
            "goal": "block losing probe contexts before unlocking more near-miss entries.",
            "must_not_do": "broaden_near_miss_before_probe_leak_is_pruned",
        },
        {
            "id": "winner_only_capacity_ablation",
            "enabled": "winner_only_capacity_ablation_needed" in gap_ids,
            "goal": "add size only after the trade validates the thesis.",
            "must_not_do": "larger_first_entry",
        },
        {
            "id": "range_structure_classifier",
            "enabled": True,
            "goal": "classify accumulation/distribution/range noise before allowing range probes.",
            "must_not_do": "subjective_label_as_direct_entry",
        },
        {
            "id": "paper_execution_parity_collection",
            "enabled": "paper_execution_parity_missing" in gap_ids,
            "goal": "prove replay-vs-paper order, fill, fee, slippage, and position lineage.",
            "must_not_do": "send_live_orders",
        },
    ]
    return order


def build_adaptive_meta_router_audit(
    *,
    walk_forward_report: dict[str, Any] | None,
    live_readiness_report: dict[str, Any] | None,
    input_walk_forward_report: str | None = None,
    input_live_readiness_report: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    readiness = _readiness_summary(live_readiness_report)
    router = _router_mode_summary(walk_forward_report)
    context = _aggregate_context_summary(walk_forward_report)
    gaps = _gap_items(readiness=readiness, router=router, context=context)
    critical = [item for item in gaps if item.get("severity") == "critical"]
    high = [item for item in gaps if item.get("severity") == "high"]
    return {
        "generated_at": generated_at.isoformat(),
        "status": "adaptive_meta_router_audit_complete",
        "no_live_order_sent": True,
        "input_walk_forward_report": input_walk_forward_report,
        "input_live_readiness_report": input_live_readiness_report,
        "policy": {
            "baseline_engine": "market_state_rotation_v6",
            "target_architecture": "adaptive_meta_router",
            "paper_only_until_execution_parity_passes": True,
            "do_not_change_strategy_by_discretionary_label_only": True,
            "mode_router_must_be_walk_forward_validated": True,
            "live_allowed_candidate_count": 0,
        },
        "current_readiness": readiness,
        "current_walk_forward_context": context,
        "router_mode_summary": router,
        "playbook_contracts": _playbook_contracts(),
        "gap_count": len(gaps),
        "critical_gap_count": len(critical),
        "high_gap_count": len(high),
        "gaps": gaps,
        "next_experiment_order": _experiment_order(gaps),
        "promotion_gates": [
            "walk_forward_oos_pass_by_mode",
            "cost_funding_slippage_stress_pass",
            "exact_30_60_90d_tail_review_pass_or_research_exception",
            "paper_execution_parity_pass_before_tiny_canary",
            "no_live_orders_from_audit_or_research_scripts",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    router = dict(report.get("router_mode_summary") or {})
    lines = [
        "# Market State Rotation V6 Adaptive Meta-Router Audit",
        "",
        f"- status: `{report.get('status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- router_contract_active: `{router.get('router_contract_active')}`",
        f"- active_modes: `{', '.join(router.get('active_modes') or [])}`",
        f"- gap_count: `{report.get('gap_count')}`",
        f"- critical_gap_count: `{report.get('critical_gap_count')}`",
        f"- high_gap_count: `{report.get('high_gap_count')}`",
        "",
        "## Gaps",
        "",
    ]
    for item in list(report.get("gaps") or []):
        lines.append(
            f"- `{item.get('id')}`: severity=`{item.get('severity')}`, "
            f"type=`{item.get('type')}`, next=`{item.get('next_action')}`"
        )
    lines.extend(["", "## Next Experiments", ""])
    for item in list(report.get("next_experiment_order") or []):
        lines.append(
            f"- `{item.get('id')}`: enabled=`{item.get('enabled')}`, goal=`{item.get('goal')}`"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build market-state rotation v6 adaptive meta-router audit.")
    parser.add_argument("--walk-forward-report", default="")
    parser.add_argument("--live-readiness-report", default=DEFAULT_LIVE_READINESS_REPORT)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    live_path = _resolve(args.live_readiness_report)
    live_report = _load_json_optional(live_path)
    walk_source = args.walk_forward_report or _walk_forward_path_from_readiness(live_report)
    walk_path = _resolve(walk_source)
    report = build_adaptive_meta_router_audit(
        walk_forward_report=_load_json_optional(walk_path),
        live_readiness_report=live_report,
        input_walk_forward_report=_display_path(walk_path),
        input_live_readiness_report=_display_path(live_path),
    )
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        assert report_dir is not None
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_adaptive_meta_router_audit.json"
        md_path = report_dir / "market_state_rotation_v6_adaptive_meta_router_audit.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
