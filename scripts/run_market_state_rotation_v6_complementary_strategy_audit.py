#!/usr/bin/env python3
"""Review complementary strategy ideas for market-state rotation v6.

This is a research-only audit. It does not enable live trading. The goal is to
separate useful complements from tempting but weak strategy blending:

* keep the current v6 engine as the baseline;
* reject external sleeves that do not clear robustness gates;
* convert similar trading ideas into narrow ambiguity-resolution overlays.
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
DEFAULT_TURTLE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_complement_turtle_btc100/latest.json"
)
DEFAULT_ENTRY_FILTER_AUDIT = (
    "reports/validation/diagnostics/market_state_rotation_v6_entry_filter_sparsity_audit/"
    "market_state_rotation_v6_entry_filter_sparsity_audit.json"
)
DEFAULT_META_ROUTER_AUDIT = (
    "reports/validation/diagnostics/market_state_rotation_v6_adaptive_meta_router_audit/"
    "market_state_rotation_v6_adaptive_meta_router_audit.json"
)


REFERENCE_PATTERNS = [
    {
        "id": "atr_donchian_trend_following",
        "source": "turtle_atr_donchian_trend_following",
        "role": "use_as_trend_state_or_runner_protection_feature_not_direct_sleeve_unless_oos_clears",
        "rationale": (
            "ATR/Donchian style complements discretionary rotation only when it protects winners or "
            "confirms one-way continuation. It should not override v6 entries after weak sleeve evidence."
        ),
    },
    {
        "id": "winner_only_pyramiding",
        "source": "pyramiding_add_to_winners",
        "role": "scale_only_after_position_is_validating_the_thesis",
        "rationale": (
            "The useful part is not larger first entries; it is delayed add capacity after realized or "
            "unrealized evidence confirms the chosen direction."
        ),
    },
    {
        "id": "wyckoff_structure_context",
        "source": "wyckoff_accumulation_distribution_reaccumulation",
        "role": "classify_ambiguous_range_contexts_before_unlocking_probes",
        "rationale": (
            "Wyckoff-like structure is useful as a range context classifier. It is too subjective to be "
            "counted as a direct live entry without a separate quantified trigger and walk-forward proof."
        ),
    },
]


def _resolve(path: str | Path) -> Path:
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _load_json_optional(path: str | Path) -> dict[str, Any] | None:
    resolved = _resolve(path)
    if not resolved.exists():
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


def _best_turtle_candidate(turtle_report: dict[str, Any] | None) -> dict[str, Any]:
    if not turtle_report:
        return {
            "available": False,
            "decision": "source_missing",
            "accepted_as_independent_sleeve": False,
            "recommended_use": "do_not_use_until_report_exists",
        }
    candidates = list(turtle_report.get("top_robust") or [])
    if not candidates:
        return {
            "available": True,
            "decision": "no_candidates",
            "accepted_as_independent_sleeve": False,
            "recommended_use": "do_not_use_until_candidates_exist",
        }
    best = dict(candidates[0])
    default_x = _float(best.get("default_x"), 1.0)
    min_x = _float(best.get("min_x"), 1.0)
    max_dd = _float(best.get("max_drawdown_pct"))
    decision_default = str(best.get("decision_default") or "")
    accepted = (
        decision_default in {"PAPER_RESEARCH", "WATCH"}
        and default_x >= 3.0
        and min_x >= 2.0
        and max_dd <= 25.0
    )
    return {
        "available": True,
        "name": best.get("name"),
        "decision": "accept_research_sleeve_candidate" if accepted else "reject_as_independent_sleeve",
        "accepted_as_independent_sleeve": accepted,
        "recommended_use": (
            "paper_research_sleeve_ablation"
            if accepted
            else "trend_state_feature_or_runner_protection_only"
        ),
        "evidence": {
            "default_x": round(default_x, 6),
            "min_x": round(min_x, 6),
            "geo_x": round(_float(best.get("geo_x"), 1.0), 6),
            "max_drawdown_pct": _pct(max_dd),
            "worst_year_pct": _pct(best.get("worst_year_pct")),
            "avg_gross_exposure": _pct(best.get("avg_gross_exposure")),
            "turnover_sum": _pct(best.get("turnover_sum")),
            "decision_default": decision_default,
        },
        "config": dict(best.get("config") or {}),
        "reject_reasons": [] if accepted else _turtle_reject_reasons(best),
    }


def _turtle_reject_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if str(candidate.get("decision_default") or "") not in {"PAPER_RESEARCH", "WATCH"}:
        reasons.append("default_decision_not_research_grade")
    if _float(candidate.get("default_x"), 1.0) < 3.0:
        reasons.append("default_return_multiple_below_3x")
    if _float(candidate.get("min_x"), 1.0) < 2.0:
        reasons.append("stress_min_multiple_below_2x")
    if _float(candidate.get("max_drawdown_pct")) > 25.0:
        reasons.append("drawdown_above_25pct")
    return reasons


def _readiness_summary(live_readiness: dict[str, Any] | None) -> dict[str, Any]:
    if not live_readiness:
        return {"available": False, "stage": "unknown", "blockers": [], "warnings": []}
    summary = dict(live_readiness.get("summary") or {})
    backlog = dict(live_readiness.get("upgrade_backlog") or {})
    return {
        "available": True,
        "stage": live_readiness.get("stage"),
        "ready_for_paper": bool(live_readiness.get("ready_for_paper")),
        "ready_for_tiny_canary": bool(live_readiness.get("ready_for_tiny_canary")),
        "ready_for_full_live": bool(live_readiness.get("ready_for_full_live")),
        "blockers": list(live_readiness.get("blockers") or []),
        "warnings": list(live_readiness.get("warnings") or []),
        "compounded_oos_return_pct": _pct(summary.get("compounded_oos_return_pct")),
        "max_oos_drawdown_pct": _pct(summary.get("max_oos_drawdown_pct")),
        "worst_exact_30d_return_pct": _pct(
            dict(dict(summary.get("worst_exact_rolling") or {}).get("30d") or {}).get(
                "worst_min_return_pct"
            )
        ),
        "upgrade_backlog_ids": [
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "priority": item.get("priority"),
            }
            for item in list(backlog.get("items") or [])
        ],
    }


def _entry_sparsity_summary(entry_filter_audit: dict[str, Any] | None) -> dict[str, Any]:
    if not entry_filter_audit:
        return {
            "available": False,
            "recommended_scope": "run_entry_filter_sparsity_audit_first",
        }
    diagnosis = dict(entry_filter_audit.get("diagnosis") or {})
    return {
        "available": True,
        "status": entry_filter_audit.get("status"),
        "recommended_scope": diagnosis.get("recommended_experiment_scope"),
        "eligible_probe_context_count": int(diagnosis.get("eligible_probe_context_count") or 0),
        "rejected_soft_context_count": int(diagnosis.get("rejected_soft_context_count") or 0),
        "mc04_broad_relaxation_rejected": bool(diagnosis.get("mc04_broad_relaxation_rejected")),
        "paper_fill_collection_will_remain_slow_without_fresh_adds": bool(
            diagnosis.get("paper_fill_collection_will_remain_slow_without_fresh_adds")
        ),
    }


def _meta_router_summary(meta_router_audit: dict[str, Any] | None) -> dict[str, Any]:
    if not meta_router_audit:
        return {
            "available": False,
            "status": "missing",
            "router_contract_active": False,
            "recommended_scope": "run_adaptive_meta_router_audit_first",
            "gap_ids": [],
            "enabled_experiment_ids": [],
        }
    router = dict(meta_router_audit.get("router_mode_summary") or {})
    gaps = list(meta_router_audit.get("gaps") or [])
    experiments = list(meta_router_audit.get("next_experiment_order") or [])
    return {
        "available": True,
        "status": meta_router_audit.get("status"),
        "router_contract_active": bool(router.get("router_contract_active")),
        "active_modes": list(router.get("active_modes") or []),
        "critical_gap_count": int(meta_router_audit.get("critical_gap_count") or 0),
        "high_gap_count": int(meta_router_audit.get("high_gap_count") or 0),
        "gap_ids": [str(item.get("id")) for item in gaps],
        "enabled_experiment_ids": [
            str(item.get("id"))
            for item in experiments
            if bool(item.get("enabled"))
        ],
    }


def _candidate_decisions(
    *,
    readiness: dict[str, Any],
    turtle: dict[str, Any],
    entry_sparsity: dict[str, Any],
    meta_router: dict[str, Any],
) -> list[dict[str, Any]]:
    backlog_ids = {str(item.get("id")) for item in readiness.get("upgrade_backlog_ids") or []}
    decisions: list[dict[str, Any]] = [
        {
            "id": "adaptive_meta_router_contract",
            "decision": (
                "promote_to_shadow_wfo_experiment"
                if "router_contract_shadow_wfo" in set(meta_router.get("enabled_experiment_ids") or [])
                else "monitor_existing_router_contract"
                if meta_router.get("router_contract_active")
                else "run_meta_router_audit_first"
            ),
            "live_allowed": False,
            "paper_allowed": bool(meta_router.get("available")),
            "recommended_role": "regime_playbook_router_before_external_strategy_blending",
            "evidence": meta_router,
            "reason": (
                "Market-adaptive behavior should be validated as explicit regime playbooks before adding "
                "external strategy sleeves or discretionary labels."
            ),
        },
        {
            "id": "external_turtle_atr_btc_sleeve",
            "decision": turtle.get("decision"),
            "live_allowed": False,
            "paper_allowed": bool(turtle.get("accepted_as_independent_sleeve")),
            "recommended_role": turtle.get("recommended_use"),
            "evidence": dict(turtle.get("evidence") or {}),
            "reason": (
                "Independent sleeve evidence is not strong enough; keep only its trend/runner-protection idea."
                if not turtle.get("accepted_as_independent_sleeve")
                else "Research sleeve clears the initial robustness gate and still needs OOS ablation against v6."
            ),
        },
        {
            "id": "wyckoff_like_structure_classifier",
            "decision": "add_as_ambiguity_classifier_candidate",
            "live_allowed": False,
            "paper_allowed": True,
            "recommended_role": "range_context_label_before_near_miss_or_base_unlock",
            "evidence": {
                "entry_sparsity_available": bool(entry_sparsity.get("available")),
                "recommended_scope": entry_sparsity.get("recommended_scope"),
            },
            "reason": (
                "Use structure labels to distinguish re-accumulation/redistribution/range noise; "
                "do not treat the label itself as an entry."
            ),
        },
        {
            "id": "quality_gated_near_miss_micro_probe",
            "decision": (
                "promote_to_walk_forward_experiment"
                if int(entry_sparsity.get("eligible_probe_context_count") or 0) > 0
                else "keep_in_backlog_until_eligible_contexts_exist"
            ),
            "live_allowed": False,
            "paper_allowed": int(entry_sparsity.get("eligible_probe_context_count") or 0) > 0,
            "recommended_role": "fresh_signal_cadence_repair_without_relaxing_hard_guards",
            "evidence": entry_sparsity,
            "reason": "Only MC12-style high-quality soft contexts can be probed; MC04 remains observe-only.",
        },
        {
            "id": "negative_base_context_pruning",
            "decision": (
                "promote_to_targeted_ablation"
                if "base_negative_context_pruning" in backlog_ids
                else "monitor"
            ),
            "live_allowed": False,
            "paper_allowed": "base_negative_context_pruning" in backlog_ids,
            "recommended_role": "suppress_only_contexts_with_negative_realized_contribution",
            "evidence": {"backlog_present": "base_negative_context_pruning" in backlog_ids},
            "reason": "This directly addresses base contexts that leak alpha without cutting the whole base engine.",
        },
        {
            "id": "one_way_runner_protection",
            "decision": (
                "promote_to_targeted_ablation"
                if "one_way_forced_trim_cost_repair" in backlog_ids
                else "monitor"
            ),
            "live_allowed": False,
            "paper_allowed": "one_way_forced_trim_cost_repair" in backlog_ids,
            "recommended_role": "delay_or_reduce_forced_trim_when_one_way_continuation_remains_confirmed",
            "evidence": {"backlog_present": "one_way_forced_trim_cost_repair" in backlog_ids},
            "reason": "This keeps the Wonyotti/Nanyotti-style runner alive when the trend thesis is still valid.",
        },
        {
            "id": "winner_only_capacity_extension",
            "decision": (
                "promote_to_capacity_ablation"
                if "single_unit_capacity_review" in backlog_ids
                else "monitor"
            ),
            "live_allowed": False,
            "paper_allowed": "single_unit_capacity_review" in backlog_ids,
            "recommended_role": "add_capacity_only_after_trade_validation_not_before",
            "evidence": {"backlog_present": "single_unit_capacity_review" in backlog_ids},
            "reason": "Capacity should be unlocked after validation, not used as bigger initial leverage.",
        },
    ]
    return decisions


def _ambiguity_resolution_matrix() -> list[dict[str, Any]]:
    return [
        {
            "ambiguous_context": "MC12_low_confluence",
            "classification": "soft_candidate",
            "allowed_repair": "quality_gated_micro_probe",
            "minimum_filters": [
                "with_trend_alignment",
                "directional_uptrend_or_downtrend_regime",
                "normal_execution_context",
                "score_above_low_bucket",
                "edge_above_low_bucket",
                "reason_stack_not_thin",
                "extension_atr_at_or_below_1p5",
                "failure_guard_and_cooldown",
            ],
            "blocked_repair": "broad_base_or_chase_relaxation",
        },
        {
            "ambiguous_context": "MC04_no_clear_first_touch",
            "classification": "broad_soft_noise",
            "allowed_repair": "observe_only_until_narrower_context_proves_edge",
            "minimum_filters": ["new_365d_or_walk_forward_evidence_required"],
            "blocked_repair": "direct_probe_or_base_unlock",
        },
        {
            "ambiguous_context": "unconfirmed_breakout_or_event_time_chase",
            "classification": "hard_guard",
            "allowed_repair": "none_without_liquidity_volume_parity_evidence",
            "minimum_filters": ["volume_or_liquidity_confirmation", "event_time_stress_pass"],
            "blocked_repair": "score_only_relaxation",
        },
        {
            "ambiguous_context": "one_way_against_forced_trim",
            "classification": "runner_vs_reversal_conflict",
            "allowed_repair": "delay_or_reduce_trim_only_when_one_way_score_and_trend_hold_confirm",
            "minimum_filters": ["one_way_score_floor", "score_diff_floor", "adverse_reaction_not_extreme"],
            "blocked_repair": "unconditional_hold_or_unconditional_flip",
        },
        {
            "ambiguous_context": "negative_base_context",
            "classification": "localized_alpha_leak",
            "allowed_repair": "context_specific_base_suppression_or_dust_size",
            "minimum_filters": ["realized_context_pnl_negative", "chase_context_not_positive"],
            "blocked_repair": "blanket_base_entry_cut",
        },
        {
            "ambiguous_context": "single_unit_capacity_saturation",
            "classification": "winner_scaling_constraint",
            "allowed_repair": "winner_only_capacity_extension_after_validation",
            "minimum_filters": ["position_in_profit_or_thesis_confirmed", "cost_drag_gate", "drawdown_gate"],
            "blocked_repair": "larger_first_entry",
        },
    ]


def build_complementary_strategy_audit(
    *,
    live_readiness_report: dict[str, Any] | None,
    turtle_report: dict[str, Any] | None,
    entry_filter_audit: dict[str, Any] | None = None,
    meta_router_audit: dict[str, Any] | None = None,
    input_live_readiness_report: str | None = None,
    input_turtle_report: str | None = None,
    input_entry_filter_audit: str | None = None,
    input_meta_router_audit: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    readiness = _readiness_summary(live_readiness_report)
    turtle = _best_turtle_candidate(turtle_report)
    entry_sparsity = _entry_sparsity_summary(entry_filter_audit)
    meta_router = _meta_router_summary(meta_router_audit)
    decisions = _candidate_decisions(
        readiness=readiness,
        turtle=turtle,
        entry_sparsity=entry_sparsity,
        meta_router=meta_router,
    )
    accepted_paper = [item for item in decisions if item.get("paper_allowed")]
    live_allowed = [item for item in decisions if item.get("live_allowed")]
    return {
        "generated_at": generated_at.isoformat(),
        "status": "complementary_strategy_audit_complete",
        "no_live_order_sent": True,
        "input_live_readiness_report": input_live_readiness_report,
        "input_turtle_report": input_turtle_report,
        "input_entry_filter_audit": input_entry_filter_audit,
        "input_meta_router_audit": input_meta_router_audit,
        "strategy_addition_policy": {
            "baseline_engine": "market_state_rotation_v6",
            "do_not_blend_external_sleeves_without_oos_ablation": True,
            "do_not_use_subjective_structure_labels_as_direct_entries": True,
            "paper_only_until_execution_parity_and_current_evidence_pass": True,
            "live_allowed_candidate_count": len(live_allowed),
            "paper_allowed_candidate_count": len(accepted_paper),
        },
        "current_v6_baseline": readiness,
        "external_reference_patterns": REFERENCE_PATTERNS,
        "external_turtle_benchmark": turtle,
        "entry_filter_sparsity": entry_sparsity,
        "adaptive_meta_router": meta_router,
        "candidate_decisions": decisions,
        "ambiguity_resolution_matrix": _ambiguity_resolution_matrix(),
        "next_experiment_order": [
            "adaptive_meta_router_contract",
            "one_way_runner_protection",
            "negative_base_context_pruning",
            "quality_gated_near_miss_micro_probe",
            "winner_only_capacity_extension",
            "wyckoff_like_structure_classifier",
            "external_turtle_atr_btc_sleeve",
        ],
        "non_negotiables": [
            "do_not_submit_live_orders_from_this_audit",
            "do_not_relax_hard_guards_with_score_only_rules",
            "do_not_add_large_initial_size_to_fix_low_return",
            "do_not_promote_external_sleeves_that_fail_research_grade",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    policy = dict(report.get("strategy_addition_policy") or {})
    turtle = dict(report.get("external_turtle_benchmark") or {})
    lines = [
        "# Market State Rotation V6 Complementary Strategy Audit",
        "",
        f"- status: `{report.get('status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- paper_allowed_candidate_count: `{policy.get('paper_allowed_candidate_count')}`",
        f"- live_allowed_candidate_count: `{policy.get('live_allowed_candidate_count')}`",
        f"- turtle decision: `{turtle.get('decision')}`",
        f"- turtle recommended use: `{turtle.get('recommended_use')}`",
        "",
        "## Candidate Decisions",
        "",
    ]
    for item in list(report.get("candidate_decisions") or []):
        lines.append(
            f"- `{item.get('id')}`: decision=`{item.get('decision')}`, "
            f"paper=`{item.get('paper_allowed')}`, live=`{item.get('live_allowed')}`, "
            f"role=`{item.get('recommended_role')}`"
        )
    lines.extend(["", "## Ambiguity Resolution", ""])
    for item in list(report.get("ambiguity_resolution_matrix") or []):
        lines.append(
            f"- `{item.get('ambiguous_context')}` -> `{item.get('allowed_repair')}` "
            f"(block `{item.get('blocked_repair')}`)"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build market-state rotation v6 complementary strategy audit.")
    parser.add_argument("--live-readiness-report", default=DEFAULT_LIVE_READINESS_REPORT)
    parser.add_argument("--turtle-report", default=DEFAULT_TURTLE_REPORT)
    parser.add_argument("--entry-filter-audit", default=DEFAULT_ENTRY_FILTER_AUDIT)
    parser.add_argument("--meta-router-audit", default=DEFAULT_META_ROUTER_AUDIT)
    parser.add_argument(
        "--report-dir",
        default="reports/validation/diagnostics/market_state_rotation_v6_complementary_strategy_audit",
    )
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    live_path = _resolve(args.live_readiness_report)
    turtle_path = _resolve(args.turtle_report)
    entry_path = _resolve(args.entry_filter_audit)
    meta_router_path = _resolve(args.meta_router_audit)
    report = build_complementary_strategy_audit(
        live_readiness_report=_load_json_optional(live_path),
        turtle_report=_load_json_optional(turtle_path),
        entry_filter_audit=_load_json_optional(entry_path),
        meta_router_audit=_load_json_optional(meta_router_path),
        input_live_readiness_report=_display_path(live_path),
        input_turtle_report=_display_path(turtle_path),
        input_entry_filter_audit=_display_path(entry_path) if entry_path.exists() else None,
        input_meta_router_audit=_display_path(meta_router_path) if meta_router_path.exists() else None,
    )
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_complementary_strategy_audit.json"
        md_path = report_dir / "market_state_rotation_v6_complementary_strategy_audit.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
