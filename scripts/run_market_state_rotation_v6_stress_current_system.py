#!/usr/bin/env python3
"""Stress the selected market-state rotation v6 walk-forward system.

This is a fast selected-model stress layer. It does not reselect candidates or
replay fills; it re-prices each stored OOS fold from gross return and modeled
cost drag so current-system fragility can be inspected before expensive reruns.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class StressScenario:
    name: str
    fee_bps_per_side: float | None = None
    slippage_bps_per_side: float | None = None
    trade_cost_multiplier: float | None = None
    funding_bps_per_8h: float = 0.0
    borrow_bps_per_day: float = 0.0


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


def _top_numeric_items(values: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(values, dict):
        return []
    rows = [
        {"name": str(key), "value": _pct(_float(value))}
        for key, value in values.items()
        if _float(value) != 0.0
    ]
    return sorted(rows, key=lambda item: abs(_float(item.get("value"))), reverse=True)[:limit]


def _compact_context(values: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(values, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in keys:
        if key not in values:
            continue
        value = values.get(key)
        if isinstance(value, float):
            compact[key] = _pct(value)
        else:
            compact[key] = value
    return compact


def _numeric_payload(values: Any) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    return {
        str(key): _pct(_float(value))
        for key, value in sorted(values.items(), key=lambda item: str(item[0]))
        if _float(value) != 0.0
    }


def _entry_context_role(name: str) -> str:
    return str(name).split("|", 1)[0]


def _context_pnl_items(
    values: Any,
    *,
    role: str,
    positive: bool | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if not isinstance(values, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key, value in values.items():
        name = str(key)
        numeric = _float(value)
        if numeric == 0.0 or _entry_context_role(name) != role:
            continue
        if positive is True and numeric <= 0.0:
            continue
        if positive is False and numeric >= 0.0:
            continue
        rows.append({"name": name, "value": _pct(numeric)})
    if positive is True:
        return sorted(rows, key=lambda item: _float(item.get("value")), reverse=True)[:limit]
    if positive is False:
        return sorted(rows, key=lambda item: _float(item.get("value")))[:limit]
    return sorted(rows, key=lambda item: abs(_float(item.get("value"))), reverse=True)[:limit]


def _count_role_contexts(values: Any, *, role: str, positive: bool) -> int:
    if not isinstance(values, dict):
        return 0
    return sum(
        1
        for key, value in values.items()
        if _entry_context_role(str(key)) == role
        and (_float(value) > 0.0 if positive else _float(value) < 0.0)
    )


def _fold_alpha_actionability(result: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(result.get("event_diagnostics") or {})
    role_pnl_raw = diagnostics.get("realized_pnl_usd_units_by_role")
    context_pnl_raw = diagnostics.get("realized_pnl_usd_units_by_entry_context")
    per_add_context_pnl_raw = diagnostics.get("realized_pnl_usd_units_per_add_by_entry_context")
    role_pnl_map = dict(role_pnl_raw) if isinstance(role_pnl_raw, dict) else {}
    add_by_role = {
        str(key): int(_float(value))
        for key, value in dict(diagnostics.get("add_by_role") or {}).items()
    }
    role_pnl = _numeric_payload(role_pnl_raw)
    base_pnl = _float(role_pnl_map.get("base"))
    probe_pnl = _float(role_pnl_map.get("probe"))
    chase_pnl = _float(role_pnl_map.get("chase"))
    positive_role_pnl = sum(max(_float(value), 0.0) for value in role_pnl_map.values())
    base_positive_share = base_pnl / positive_role_pnl if positive_role_pnl > 0.0 else None
    probe_loss_to_base_pnl_ratio = (
        abs(min(probe_pnl, 0.0)) / abs(base_pnl)
        if base_pnl != 0.0 and probe_pnl < 0.0
        else None
    )
    base_positive_contexts = _count_role_contexts(context_pnl_raw, role="base", positive=True)
    base_negative_contexts = _count_role_contexts(context_pnl_raw, role="base", positive=False)
    probe_positive_contexts = _count_role_contexts(context_pnl_raw, role="probe", positive=True)
    probe_negative_contexts = _count_role_contexts(context_pnl_raw, role="probe", positive=False)
    chase_positive_contexts = _count_role_contexts(context_pnl_raw, role="chase", positive=True)
    chase_negative_contexts = _count_role_contexts(context_pnl_raw, role="chase", positive=False)
    positive_base_alpha = (
        base_pnl > 0.0
        and (base_positive_share is None or base_positive_share >= 0.35)
        and base_positive_contexts >= max(base_negative_contexts, 1)
    )
    negative_probe_alpha = probe_pnl < 0.0 or (
        probe_negative_contexts > 0 and probe_negative_contexts >= probe_positive_contexts
    )
    tiny_negative_probe_alpha = bool(
        negative_probe_alpha
        and probe_loss_to_base_pnl_ratio is not None
        and probe_loss_to_base_pnl_ratio < 0.005
    )
    positive_chase_alpha = (
        chase_pnl > 0.0
        and chase_positive_contexts >= max(chase_negative_contexts, 1)
    )
    notes: list[str] = []
    if positive_base_alpha:
        notes.append("base_role_has_positive_realized_pnl")
    if negative_probe_alpha:
        notes.append("probe_role_or_context_has_negative_realized_pnl")
    if tiny_negative_probe_alpha:
        notes.append("probe_loss_is_tiny_vs_base_realized_pnl")
    if positive_chase_alpha:
        notes.append("chase_role_has_positive_realized_pnl")
    if base_negative_contexts > 0:
        notes.append("base_has_negative_context_pockets")
    return {
        "role_pnl_usd_units": role_pnl,
        "add_by_role": add_by_role,
        "base_role_pnl_usd_units": _pct(base_pnl),
        "probe_role_pnl_usd_units": _pct(probe_pnl),
        "chase_role_pnl_usd_units": _pct(chase_pnl),
        "base_positive_pnl_share": (
            round(float(base_positive_share), 4) if base_positive_share is not None else None
        ),
        "probe_loss_to_base_pnl_ratio": (
            round(float(probe_loss_to_base_pnl_ratio), 6)
            if probe_loss_to_base_pnl_ratio is not None
            else None
        ),
        "base_context_positive_count": base_positive_contexts,
        "base_context_negative_count": base_negative_contexts,
        "probe_context_positive_count": probe_positive_contexts,
        "probe_context_negative_count": probe_negative_contexts,
        "chase_context_positive_count": chase_positive_contexts,
        "chase_context_negative_count": chase_negative_contexts,
        "positive_base_alpha": positive_base_alpha,
        "negative_probe_alpha": negative_probe_alpha,
        "tiny_negative_probe_alpha": tiny_negative_probe_alpha,
        "positive_chase_alpha": positive_chase_alpha,
        "best_base_contexts": _context_pnl_items(context_pnl_raw, role="base", positive=True),
        "worst_base_contexts": _context_pnl_items(context_pnl_raw, role="base", positive=False),
        "best_probe_contexts": _context_pnl_items(context_pnl_raw, role="probe", positive=True),
        "worst_probe_contexts": _context_pnl_items(context_pnl_raw, role="probe", positive=False),
        "worst_probe_contexts_per_add": _context_pnl_items(
            per_add_context_pnl_raw,
            role="probe",
            positive=False,
        ),
        "notes": notes,
    }


def _fold_event_structure(result: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(result.get("event_diagnostics") or {})
    ratios = dict(diagnostics.get("ratios") or {})
    ratio_keys = (
        "turnover_events_per_add",
        "one_way_forced_trim_per_add",
        "reaction_trim_per_remove",
        "repair_stop_per_add",
        "probe_add_per_add",
        "chase_add_per_add",
    )
    return {
        "health": diagnostics.get("health"),
        "flags": list(diagnostics.get("flags") or []),
        "borderline_flags": list(diagnostics.get("borderline_flags") or []),
        "add_events": int(diagnostics.get("add_events") or 0),
        "remove_events": int(diagnostics.get("remove_events") or 0),
        "ratios": {
            key: _pct(_float(ratios.get(key)))
            for key in ratio_keys
            if key in ratios
        },
        "side_imbalance": _compact_context(
            diagnostics.get("side_imbalance_context"),
            (
                "status",
                "dominant_side",
                "dominant_side_share",
                "directional_adds",
            ),
        ),
        "role_concentration": _compact_context(
            diagnostics.get("role_concentration_context"),
            (
                "status",
                "dominant_role",
                "dominant_role_share",
                "role_adds",
                "add_by_role",
            ),
        ),
        "month_concentration": _compact_context(
            diagnostics.get("month_concentration_context"),
            (
                "status",
                "dominant_month",
                "dominant_month_share",
                "active_months",
                "total_months",
            ),
        ),
        "capacity": _compact_context(
            diagnostics.get("capacity_structure_context"),
            (
                "status",
                "scale_in_capacity_available",
                "max_possible_units",
                "base_max_units",
                "capacity_after_first_base_units",
            ),
        ),
    }


def _fold_regime_structure(result: dict[str, Any]) -> dict[str, Any]:
    regimes = dict(result.get("regime_performance") or {})
    rows: list[dict[str, Any]] = []
    for regime, payload in regimes.items():
        if not isinstance(payload, dict):
            continue
        rows.append(
            {
                "regime": str(regime),
                "return_pct": _pct(_float(payload.get("return_pct"))),
                "drawdown_pct": _pct(_float(payload.get("max_drawdown_pct"))),
                "add_events": int(payload.get("add_events") or 0),
                "remove_events": int(payload.get("remove_events") or 0),
                "avg_abs_account_exposure": _pct(_float(payload.get("avg_abs_account_exposure"))),
            }
        )
    return {
        "top_return_regimes": sorted(
            rows,
            key=lambda item: _float(item.get("return_pct")),
            reverse=True,
        )[:3],
        "worst_drawdown_regimes": sorted(
            rows,
            key=lambda item: _float(item.get("drawdown_pct")),
            reverse=True,
        )[:3],
        "most_active_regimes": sorted(
            rows,
            key=lambda item: int(item.get("add_events") or 0),
            reverse=True,
        )[:3],
    }


def _fold_cost_structure(result: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(result.get("cost_diagnostics") or {})
    return {
        "modeled_trade_cost_pct": _pct(_float(diagnostics.get("modeled_trade_cost_pct"))),
        "modeled_carry_cost_pct": _pct(_float(diagnostics.get("modeled_carry_cost_pct"))),
        "top_by_reason_pct": _top_numeric_items(diagnostics.get("by_reason_pct")),
        "top_by_action_reason_pct": _top_numeric_items(diagnostics.get("by_action_reason_pct")),
        "top_by_action_role_pct": _top_numeric_items(diagnostics.get("by_action_role_pct")),
        "by_role_pct": _top_numeric_items(diagnostics.get("by_role_pct"), limit=4),
        "by_side_pct": _top_numeric_items(diagnostics.get("by_side_pct"), limit=4),
    }


def _fold_root_causes(
    *,
    gross_return: float,
    baseline_cost: float,
    stressed_return: float,
    dd_proxy: float,
    breakeven_cost_multiplier: float | None,
    cost_structure: dict[str, Any],
    event_structure: dict[str, Any],
    alpha_actionability: dict[str, Any],
) -> list[str]:
    causes: list[str] = []
    cost_to_gross = baseline_cost / gross_return if gross_return > 0 else float("inf")
    top_reason_values = {
        str(item.get("name")): _float(item.get("value"))
        for item in cost_structure.get("top_by_reason_pct") or []
        if isinstance(item, dict)
    }
    ratios = dict(event_structure.get("ratios") or {})
    capacity = dict(event_structure.get("capacity") or {})
    if breakeven_cost_multiplier is not None and breakeven_cost_multiplier < 3.25:
        causes.append("thin_cost_buffer_lt_3_25x")
    if cost_to_gross >= 0.30:
        causes.append("cost_consumes_30pct_gross")
    if baseline_cost >= 8.0:
        causes.append("high_oos_cost_drag_ge_8pct")
    if top_reason_values.get("base_entry", 0.0) >= 2.0:
        causes.append("base_entry_cost_ge_2pct")
    if top_reason_values.get("v6_reaction_inventory_trim", 0.0) >= 1.5:
        causes.append("reaction_trim_cost_ge_1_5pct")
    if top_reason_values.get("one_way_against_forced_trim", 0.0) >= 0.75:
        causes.append("one_way_against_forced_trim_cost_ge_0_75pct")
    if alpha_actionability.get("negative_probe_alpha"):
        causes.append("probe_realized_pnl_negative")
    if int(alpha_actionability.get("base_context_negative_count") or 0) > 0:
        causes.append("base_negative_context_pockets")
    if _float(ratios.get("turnover_events_per_add")) >= 2.4:
        causes.append("high_turnover_per_add_ge_2_4")
    if capacity.get("scale_in_capacity_available") is False:
        causes.append("single_unit_capacity_saturated")
    if stressed_return <= 0.0:
        causes.append("stress_breaks_positive_return")
    elif stressed_return <= 5.0:
        causes.append("low_stress_return_buffer_le_5pct")
    if dd_proxy >= 35.0:
        causes.append("stress_dd_proxy_ge_35pct")
    return causes


def _fold_tradeoff_tags(
    *,
    gross_return: float,
    baseline_return: float,
    baseline_cost: float,
    stressed_return: float,
    dd_proxy: float,
    breakeven_cost_multiplier: float | None,
    cost_structure: dict[str, Any],
    event_structure: dict[str, Any],
    alpha_actionability: dict[str, Any],
) -> list[str]:
    tags: list[str] = []
    cost_to_gross = baseline_cost / gross_return if gross_return > 0 else float("inf")
    top_reason_values = {
        str(item.get("name")): _float(item.get("value"))
        for item in cost_structure.get("top_by_reason_pct") or []
        if isinstance(item, dict)
    }
    capacity = dict(event_structure.get("capacity") or {})
    breakeven = breakeven_cost_multiplier or 0.0
    if baseline_return >= 50.0 and gross_return >= 60.0:
        tags.append("alpha_engine_high_return")
    if baseline_cost >= 20.0 and baseline_return >= 75.0 and breakeven >= 5.0 and stressed_return >= 25.0:
        tags.append("high_cost_high_alpha_engine")
    if cost_to_gross <= 0.20 and breakeven >= 5.0:
        tags.append("wide_cost_buffer")
    if dd_proxy >= 35.0 and stressed_return >= 50.0:
        tags.append("dd_proxy_from_cost_stress_not_return_failure")
    if capacity.get("scale_in_capacity_available") is False and baseline_return >= 50.0:
        tags.append("saturated_single_unit_alpha_engine")
    if (
        top_reason_values.get("base_entry", 0.0) >= 2.0
        and alpha_actionability.get("positive_base_alpha")
    ):
        tags.append("base_entry_cost_is_alpha_engine")
    if top_reason_values.get("v6_reaction_inventory_trim", 0.0) >= 1.5 and baseline_return >= 50.0:
        tags.append("reaction_trim_part_of_alpha_engine")
    if alpha_actionability.get("negative_probe_alpha"):
        tags.append("probe_alpha_leak")
    if alpha_actionability.get("tiny_negative_probe_alpha"):
        tags.append("probe_leak_tiny_vs_base_alpha")
    if alpha_actionability.get("positive_chase_alpha"):
        tags.append("chase_context_adds_alpha")
    if int(alpha_actionability.get("base_context_negative_count") or 0) > 0:
        tags.append("selective_base_context_pruning_candidate")
    if stressed_return <= 5.0 and breakeven < 3.25:
        tags.append("fragility_needs_cost_or_entry_cut")
    return tags


def _fold_remediation_hints(
    *,
    root_causes: list[str],
    tradeoff_tags: list[str],
) -> list[str]:
    hints: list[str] = []
    cause_set = set(root_causes)
    tag_set = set(tradeoff_tags)
    if "high_cost_high_alpha_engine" in tag_set:
        hints.append("test_right_sizing_or_staggered_scale_out_before_blanket_cost_cuts")
    if "dd_proxy_from_cost_stress_not_return_failure" in tag_set:
        hints.append("validate_replay_drawdown_before_killing_alpha")
    if "saturated_single_unit_alpha_engine" in tag_set:
        hints.append("test_selective_capacity_extension_with_dd_guard")
    if "base_entry_cost_is_alpha_engine" in tag_set:
        hints.append("avoid_blanket_base_entry_cuts")
    if "probe_alpha_leak" in tag_set:
        if "probe_leak_tiny_vs_base_alpha" in tag_set:
            hints.append("treat_probe_suppression_as_distribution_tradeoff")
        else:
            hints.append("test_probe_suppression_before_base_cuts")
    if "selective_base_context_pruning_candidate" in tag_set:
        hints.append("test_negative_base_context_filter_only")
    if "chase_context_adds_alpha" in tag_set:
        hints.append("preserve_positive_chase_contexts")
    if "fragility_needs_cost_or_entry_cut" in tag_set or "stress_breaks_positive_return" in cause_set:
        if "base_entry_cost_is_alpha_engine" in tag_set:
            hints.append("cut_marginal_probe_or_negative_context_entries")
        else:
            hints.append("cut_marginal_entries_or_reduce_turnover")
    if "low_stress_return_buffer_le_5pct" in cause_set:
        hints.append("raise_min_stress_return_before_adding_frequency")
    if "thin_cost_buffer_lt_3_25x" in cause_set and "wide_cost_buffer" not in tag_set:
        hints.append("increase_breakeven_buffer_before_adding_frequency")
    return hints


def _fold_source_diagnostics(
    fold: dict[str, Any],
    result: dict[str, Any],
    *,
    gross_return: float,
    baseline_cost: float,
    stressed_return: float,
    dd_proxy: float,
    breakeven_cost_multiplier: float | None,
) -> dict[str, Any]:
    selected_train = dict(fold.get("selected_train_result") or {})
    cost_structure = _fold_cost_structure(result)
    event_structure = _fold_event_structure(result)
    alpha_actionability = _fold_alpha_actionability(result)
    baseline_return = _float(result.get("total_return_pct"))
    root_causes = _fold_root_causes(
        gross_return=gross_return,
        baseline_cost=baseline_cost,
        stressed_return=stressed_return,
        dd_proxy=dd_proxy,
        breakeven_cost_multiplier=breakeven_cost_multiplier,
        cost_structure=cost_structure,
        event_structure=event_structure,
        alpha_actionability=alpha_actionability,
    )
    tradeoff_tags = _fold_tradeoff_tags(
        gross_return=gross_return,
        baseline_return=baseline_return,
        baseline_cost=baseline_cost,
        stressed_return=stressed_return,
        dd_proxy=dd_proxy,
        breakeven_cost_multiplier=breakeven_cost_multiplier,
        cost_structure=cost_structure,
        event_structure=event_structure,
        alpha_actionability=alpha_actionability,
    )
    return {
        "selected_model_id": fold.get("selected_model_id") or result.get("model_id"),
        "after_selection_overlays_applied": list(fold.get("after_selection_overlays_applied") or []),
        "train_snapshot": {
            "return_pct": _pct(_float(selected_train.get("total_return_pct"))),
            "gross_return_pct": _pct(_float(selected_train.get("gross_return_pct_before_costs"))),
            "cost_drag_pct": _pct(_fold_cost_drag_pct(selected_train)),
            "max_drawdown_pct": _pct(_float(selected_train.get("max_drawdown_pct"))),
            "trade_like_events": int(selected_train.get("trade_like_events") or 0),
        },
        "cost_to_gross_ratio": round(
            baseline_cost / gross_return,
            4,
        )
        if gross_return > 0
        else None,
        "cost_structure": cost_structure,
        "event_structure": event_structure,
        "alpha_actionability": alpha_actionability,
        "regime_structure": _fold_regime_structure(result),
        "root_causes": root_causes,
        "tradeoff_tags": tradeoff_tags,
        "remediation_hints": _fold_remediation_hints(
            root_causes=root_causes,
            tradeoff_tags=tradeoff_tags,
        ),
    }


def _default_scenarios(base_cost_bps_per_side: float) -> list[StressScenario]:
    if base_cost_bps_per_side <= 0:
        return [
            StressScenario("baseline", trade_cost_multiplier=1.0),
            StressScenario("cost_x1_5", trade_cost_multiplier=1.5),
            StressScenario("cost_x2_0", trade_cost_multiplier=2.0),
            StressScenario("cost_x3_0", trade_cost_multiplier=3.0),
        ]
    return [
        StressScenario("baseline", trade_cost_multiplier=1.0),
        StressScenario("fee6_slip2", fee_bps_per_side=6.0, slippage_bps_per_side=2.0),
        StressScenario("fee6_slip4", fee_bps_per_side=6.0, slippage_bps_per_side=4.0),
        StressScenario("cost_x2_funding1", trade_cost_multiplier=2.0, funding_bps_per_8h=1.0),
        StressScenario("cost_x2_funding3", trade_cost_multiplier=2.0, funding_bps_per_8h=3.0),
        StressScenario("cost_x3_funding3", trade_cost_multiplier=3.0, funding_bps_per_8h=3.0),
    ]


def _parse_scenario(value: str) -> StressScenario:
    parts = value.split(":")
    if len(parts) not in {2, 4, 5}:
        raise argparse.ArgumentTypeError(
            "scenario must be name:cost_mult or name:fee_bps:slip_bps:funding_bps[:borrow_bps_day]"
        )
    name = parts[0].strip()
    if not name:
        raise argparse.ArgumentTypeError("scenario name cannot be empty")
    if len(parts) == 2:
        return StressScenario(name=name, trade_cost_multiplier=float(parts[1]))
    return StressScenario(
        name=name,
        fee_bps_per_side=float(parts[1]),
        slippage_bps_per_side=float(parts[2]),
        funding_bps_per_8h=float(parts[3]),
        borrow_bps_per_day=float(parts[4]) if len(parts) == 5 else 0.0,
    )


def _scenario_cost_multiplier(
    scenario: StressScenario,
    *,
    base_cost_bps_per_side: float,
) -> float:
    if scenario.trade_cost_multiplier is not None:
        return max(float(scenario.trade_cost_multiplier), 0.0)
    scenario_cost = max(float(scenario.fee_bps_per_side or 0.0), 0.0) + max(
        float(scenario.slippage_bps_per_side or 0.0),
        0.0,
    )
    if base_cost_bps_per_side <= 0:
        return 1.0
    return max(scenario_cost / base_cost_bps_per_side, 0.0)


def _fold_cost_drag_pct(result: dict[str, Any]) -> float:
    gross = _float(result.get("gross_return_pct_before_costs"))
    net = _float(result.get("total_return_pct"))
    direct = _float(result.get("estimated_cost_drag_pct"))
    implied = gross - net
    if direct > 0:
        return direct
    return max(implied, 0.0)


def _fold_carry_drag_pct(
    result: dict[str, Any],
    *,
    funding_bps_per_8h: float,
    borrow_bps_per_day: float,
) -> float:
    avg_abs_exposure = _float(result.get("avg_abs_account_exposure"))
    years = _float(result.get("years"))
    funding_fraction = max(float(funding_bps_per_8h), 0.0) / 10_000.0
    borrow_fraction = max(float(borrow_bps_per_day), 0.0) / 10_000.0
    carry_fraction = avg_abs_exposure * years * (
        funding_fraction * 3.0 * 365.0 + borrow_fraction * 365.0
    )
    return carry_fraction * 100.0


def _stress_floor_gap(
    *,
    stressed_return: float,
    baseline_cost: float,
    gross_return: float,
    carry_drag: float,
    cost_multiplier: float,
    floor_return_pct: float = 5.0,
) -> dict[str, Any]:
    gap = max(float(floor_return_pct) - stressed_return, 0.0)
    cost_reduction = gap / cost_multiplier if cost_multiplier > 0 else None
    target_baseline_cost = None
    floor_reachable_by_cost_cut = None
    if cost_multiplier > 0:
        floor_reachable_by_cost_cut = gross_return - carry_drag - float(floor_return_pct) >= 0.0
        target_baseline_cost = max(
            (gross_return - carry_drag - float(floor_return_pct)) / cost_multiplier,
            0.0,
        )
    return {
        "floor_return_pct": _pct(float(floor_return_pct)),
        "stress_buffer_to_floor_pct": _pct(stressed_return - float(floor_return_pct)),
        "gross_return_gain_needed_pct": _pct(gap),
        "baseline_cost_reduction_needed_pct": (
            _pct(float(cost_reduction)) if cost_reduction is not None else None
        ),
        "target_baseline_cost_drag_pct": (
            _pct(float(target_baseline_cost)) if target_baseline_cost is not None else None
        ),
        "floor_reachable_by_cost_cut": floor_reachable_by_cost_cut,
        "target_baseline_cost_reduction_share": (
            round(max(baseline_cost - float(target_baseline_cost), 0.0) / baseline_cost, 4)
            if target_baseline_cost is not None and baseline_cost > 0
            else None
        ),
    }


def _cost_cut_capacity_for_reason(
    reason: str,
    *,
    tradeoff_tags: set[str],
    root_causes: set[str],
) -> tuple[float, int, str]:
    if "probe" in reason:
        if "probe_alpha_leak" in tradeoff_tags and "probe_leak_tiny_vs_base_alpha" not in tradeoff_tags:
            return 0.75, 1, "negative probe leak can be suppressed before touching base alpha"
        return 0.35, 4, "probe cost cut is capped because probe loss is small or mixed"
    if reason == "hard_intraday_time_exit":
        return 0.50, 2, "time-exit flow can be made more selective or more passive"
    if reason == "one_way_against_forced_trim":
        return 0.50, 2, "one-way forced trims are a direct stress-floor target"
    if reason == "v6_reaction_inventory_trim":
        if "reaction_trim_part_of_alpha_engine" in tradeoff_tags:
            return 0.25, 5, "reaction trim participates in high-return alpha, so only small cuts are allowed"
        return 0.35, 3, "reaction trim turnover can be tightened without blocking base entries"
    if reason in {"loss_rotation_repair_trim", "repair_efficiency_stop_trim"}:
        return 0.25, 4, "repair exits are risk controls, so cuts must stay conservative"
    if reason == "base_entry":
        if "base_entry_cost_is_alpha_engine" in tradeoff_tags:
            return 0.25, 6, "base entries are alpha-positive, so cut only marginal base contexts"
        if "base_negative_context_pockets" in root_causes:
            return 0.50, 3, "base has negative context pockets that can be filtered selectively"
        return 0.35, 4, "base entry cost can be reduced only by selectivity, not a blanket cut"
    if "chase" in reason:
        if "chase_context_adds_alpha" in tradeoff_tags:
            return 0.10, 7, "chase context is positive alpha and should mostly be preserved"
        return 0.30, 5, "chase cost is cut only after cheaper fixes"
    return 0.20, 5, "generic turnover cut candidate"


def _targeted_cost_reduction_plan(row: dict[str, Any]) -> dict[str, Any]:
    floor = dict(row.get("stress_floor") or {})
    cost_multiplier = _float(row.get("trade_cost_multiplier"), 1.0)
    gross_gap = _float(floor.get("gross_return_gain_needed_pct"))
    needed = gross_gap / cost_multiplier if cost_multiplier > 0.0 else _float(
        floor.get("baseline_cost_reduction_needed_pct")
    )
    stressed_return = _float(row.get("stressed_return_pct"))
    if needed <= 0.0:
        return {
            "needed_baseline_cost_cut_pct": 0.0,
            "planned_baseline_cost_cut_pct": 0.0,
            "projected_stressed_return_pct": _pct(stressed_return),
            "target_reached": True,
            "steps": [],
        }
    tradeoff_tags = {str(item) for item in row.get("tradeoff_tags") or []}
    root_causes = {str(item) for item in row.get("root_causes") or []}
    candidates: list[dict[str, Any]] = []
    for item in row.get("top_cost_reasons") or []:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("name") or "")
        cost_pct = _float(item.get("value"))
        if not reason or cost_pct <= 0.0:
            continue
        max_share, priority, rationale = _cost_cut_capacity_for_reason(
            reason,
            tradeoff_tags=tradeoff_tags,
            root_causes=root_causes,
        )
        candidates.append(
            {
                "reason": reason,
                "available_cost_pct": _pct(cost_pct),
                "max_cut_share": round(max_share, 4),
                "max_baseline_cost_cut_pct": _pct(cost_pct * max_share),
                "priority": priority,
                "rationale": rationale,
            }
        )
    candidates.sort(key=lambda item: (int(item["priority"]), -_float(item["max_baseline_cost_cut_pct"])))

    remaining = needed
    planned = 0.0
    steps: list[dict[str, Any]] = []
    for candidate in candidates:
        if remaining <= 1e-12:
            break
        max_cut = _float(candidate.get("max_baseline_cost_cut_pct"))
        cut = min(max_cut, remaining)
        if cut <= 0.0:
            continue
        available = _float(candidate.get("available_cost_pct"))
        steps.append(
            {
                **candidate,
                "planned_baseline_cost_cut_pct": _pct(cut),
                "planned_cut_share_of_reason": round(cut / available, 4) if available > 0.0 else None,
                "projected_stressed_return_gain_pct": _pct(cut * cost_multiplier),
            }
        )
        planned += cut
        remaining -= cut
    projected = stressed_return + planned * cost_multiplier
    return {
        "needed_baseline_cost_cut_pct": _pct(needed),
        "planned_baseline_cost_cut_pct": _pct(planned),
        "remaining_baseline_cost_cut_pct": _pct(max(needed - planned, 0.0)),
        "projected_stressed_return_pct": _pct(projected),
        "target_reached": planned + 1e-9 >= needed,
        "steps": steps,
    }


def _stress_fold(
    fold: dict[str, Any],
    scenario: StressScenario,
    *,
    base_cost_bps_per_side: float,
) -> dict[str, Any]:
    result = dict(fold.get("test_result") or {})
    gross_return = _float(result.get("gross_return_pct_before_costs"))
    baseline_return = _float(result.get("total_return_pct"))
    baseline_dd = _float(result.get("max_drawdown_pct"))
    baseline_cost = _fold_cost_drag_pct(result)
    cost_multiplier = _scenario_cost_multiplier(
        scenario,
        base_cost_bps_per_side=base_cost_bps_per_side,
    )
    carry_drag = _fold_carry_drag_pct(
        result,
        funding_bps_per_8h=scenario.funding_bps_per_8h,
        borrow_bps_per_day=scenario.borrow_bps_per_day,
    )
    stressed_cost = baseline_cost * cost_multiplier
    stressed_return = gross_return - stressed_cost - carry_drag
    extra_drag = max(stressed_cost + carry_drag - baseline_cost, 0.0)
    dd_proxy = min(max(baseline_dd + extra_drag, baseline_dd), 99.9)
    breakeven_cost_multiplier = None
    if baseline_cost > 0:
        breakeven_cost_multiplier = gross_return / baseline_cost
    floor_gap = _stress_floor_gap(
        stressed_return=stressed_return,
        baseline_cost=baseline_cost,
        gross_return=gross_return,
        carry_drag=carry_drag,
        cost_multiplier=cost_multiplier,
    )
    diagnostics = _fold_source_diagnostics(
        fold,
        result,
        gross_return=gross_return,
        baseline_cost=baseline_cost,
        stressed_return=stressed_return,
        dd_proxy=dd_proxy,
        breakeven_cost_multiplier=breakeven_cost_multiplier,
    )
    row = {
        "fold": int(fold.get("fold") or 0),
        "test_start": fold.get("test_start"),
        "test_end": fold.get("test_end"),
        "baseline_return_pct": _pct(baseline_return),
        "gross_return_pct": _pct(gross_return),
        "baseline_cost_drag_pct": _pct(baseline_cost),
        "trade_cost_multiplier": round(cost_multiplier, 6),
        "carry_drag_pct": _pct(carry_drag),
        "stressed_return_pct": _pct(stressed_return),
        "return_delta_pct": _pct(stressed_return - baseline_return),
        "baseline_drawdown_pct": _pct(baseline_dd),
        "drawdown_proxy_pct": _pct(dd_proxy),
        "stress_floor": floor_gap,
        "trade_like_events": int(result.get("trade_like_events") or 0),
        "breakeven_cost_multiplier": (
            round(float(breakeven_cost_multiplier), 4)
            if breakeven_cost_multiplier is not None
            else None
        ),
        "cost_to_gross_ratio": diagnostics.get("cost_to_gross_ratio"),
        "root_causes": diagnostics.get("root_causes") or [],
        "tradeoff_tags": diagnostics.get("tradeoff_tags") or [],
        "remediation_hints": diagnostics.get("remediation_hints") or [],
        "top_cost_reasons": diagnostics.get("cost_structure", {}).get("top_by_reason_pct", [])[:3],
        "source_diagnostics": diagnostics,
    }
    row["targeted_cost_reduction_plan"] = _targeted_cost_reduction_plan(row)
    return row


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _scenario_cost_rate(scenario: StressScenario, *, base_cost_bps_per_side: float) -> float:
    if scenario.trade_cost_multiplier is not None:
        cost_bps = base_cost_bps_per_side * max(float(scenario.trade_cost_multiplier), 0.0)
    else:
        cost_bps = max(float(scenario.fee_bps_per_side or 0.0), 0.0) + max(
            float(scenario.slippage_bps_per_side or 0.0),
            0.0,
        )
    return max(cost_bps, 0.0) / 10_000.0


def _replay_load_days(
    source_report: dict[str, Any],
    *,
    requested_load_days: int | None,
    earliest_start: datetime | None,
) -> int:
    if requested_load_days is not None and requested_load_days > 0:
        return int(requested_load_days)
    source_args = dict(source_report.get("args") or {})
    overrides = dict(source_report.get("config_overrides") or {})
    load_days = int(overrides.get("load_days") or source_args.get("load_days") or 1830)
    if earliest_start is not None:
        age_days = int((datetime.now(UTC) - earliest_start).total_seconds() / 86_400.0) + 7
        load_days = max(load_days, age_days)
    return load_days


def _attach_replayed_selected_oos_metrics(
    scenario_payload: dict[str, Any],
    source_report: dict[str, Any],
    *,
    scenario_list: list[StressScenario],
    base_cost_bps_per_side: float,
    cache_dir: str | None,
    base_url: str | None,
    load_days: int | None,
    min_periods: int,
    sleep_seconds: float,
) -> dict[str, Any]:
    # Imported lazily so the fast report path stays lightweight and unit tests do
    # not need the data-loading stack unless replay is explicitly requested.
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    import scripts.run_market_state_rotation_v6_walk_forward_validation as wf

    source_args = dict(source_report.get("args") or {})
    symbol = str(source_args.get("symbol") or source_report.get("symbol") or "BTCUSDT")
    exec_interval = str(source_args.get("exec_interval") or source_report.get("exec_interval") or "5m")
    scenario_intervals = wf._csv(
        str(source_args.get("scenario_intervals") or "")
        or ",".join(
            str(item)
            for item in dict(
                dict((source_report.get("folds") or [{}])[0]).get("test_meta") or {}
            ).get("scenario_rows", {"1h": 0, "4h": 0})
        )
        or "1h,4h"
    )
    if not scenario_intervals:
        scenario_intervals = ["1h", "4h"]

    starts = [
        _parse_dt((fold.get("test_meta") or {}).get("exec_start") or fold.get("test_start_at"))
        for fold in source_report.get("folds") or []
    ]
    starts = [item for item in starts if item is not None]
    effective_load_days = _replay_load_days(
        source_report,
        requested_load_days=load_days,
        earliest_start=min(starts) if starts else None,
    )
    settings = wf.get_settings()
    resolved_base_url = str(
        base_url
        or source_args.get("base_url")
        or settings.binance_rest_base_url
        or "https://fapi.binance.com"
    ).rstrip("/")
    resolved_cache_dir = Path(
        cache_dir
        or source_args.get("cache_dir")
        or "reports/validation/btc_flip_rotation_search/cache"
    )
    if not resolved_cache_dir.is_absolute():
        resolved_cache_dir = ROOT_DIR / resolved_cache_dir

    exec_bars_all = wf._load_bars(
        symbol=symbol,
        interval=exec_interval,
        days=effective_load_days,
        cache_dir=resolved_cache_dir,
        base_url=resolved_base_url,
        sleep_seconds=sleep_seconds,
    )
    scenario_bars_all = {
        interval: wf._load_bars(
            symbol=symbol,
            interval=interval,
            days=effective_load_days,
            cache_dir=resolved_cache_dir,
            base_url=resolved_base_url,
            sleep_seconds=sleep_seconds,
        )
        for interval in scenario_intervals
    }
    folds_by_id = {int(fold.get("fold") or 0): dict(fold or {}) for fold in source_report.get("folds") or []}
    replay_summary: dict[str, Any] = {
        "enabled": True,
        "method": "selected_config_oos_rerun_with_stressed_costs",
        "symbol": symbol,
        "exec_interval": exec_interval,
        "scenario_intervals": scenario_intervals,
        "load_days": effective_load_days,
        "min_periods": int(min_periods),
        "cache_dir": str(resolved_cache_dir),
        "scenario_count": len(scenario_list),
        "fold_count": len(folds_by_id),
        "failed_replay_count": 0,
        "failures": [],
    }
    for scenario in scenario_list:
        payload = scenario_payload.get(scenario.name)
        if not isinstance(payload, dict):
            continue
        rows = list(payload.get("folds") or [])
        scenario_cost_rate = _scenario_cost_rate(
            scenario,
            base_cost_bps_per_side=base_cost_bps_per_side,
        )
        scenario_carry_rate = wf._carry_rate_per_bar(
            exec_interval=exec_interval,
            funding_bps_per_8h=float(scenario.funding_bps_per_8h),
            borrow_bps_per_day=float(scenario.borrow_bps_per_day),
        )
        for row in rows:
            fold_id = int(row.get("fold") or 0)
            fold = folds_by_id.get(fold_id) or {}
            result = dict(fold.get("test_result") or {})
            config_payload = dict(result.get("config") or {})
            start = _parse_dt((fold.get("test_meta") or {}).get("exec_start") or fold.get("test_start_at"))
            end = _parse_dt(fold.get("test_end_at"))
            if end is None:
                end = _parse_dt(fold.get("test_end"))
            if not config_payload or start is None or end is None:
                replay_summary["failed_replay_count"] += 1
                replay_summary["failures"].append(
                    {"scenario": scenario.name, "fold": fold_id, "reason": "missing_config_or_window"}
                )
                row["replay_selected_oos"] = {
                    "status": "failed",
                    "reason": "missing_config_or_window",
                }
                continue
            try:
                features, scenario_features, scenario_maps, meta = wf._window_feature_sets(
                    exec_bars_all=exec_bars_all,
                    scenario_bars_all=scenario_bars_all,
                    start=start,
                    end=end,
                    scenario_intervals=scenario_intervals,
                )
                replay_result = wf._run_config(
                    symbol=symbol,
                    features=features,
                    scenario_features=scenario_features,
                    scenario_maps=scenario_maps,
                    config=wf.MarketStateConfig(**config_payload),
                    cost_rate=scenario_cost_rate,
                    carry_rate_per_bar=scenario_carry_rate,
                    min_periods=int(min_periods),
                )
            except Exception as exc:  # pragma: no cover - defensive around data/replay IO
                replay_result = None
                failure_reason = f"exception:{type(exc).__name__}"
            else:
                failure_reason = "replay_returned_none"
            if not replay_result:
                replay_summary["failed_replay_count"] += 1
                replay_summary["failures"].append(
                    {"scenario": scenario.name, "fold": fold_id, "reason": failure_reason}
                )
                row["replay_selected_oos"] = {"status": "failed", "reason": failure_reason}
                continue
            row["replay_selected_oos"] = {
                "status": "ok",
                "return_pct": _pct(_float(replay_result.get("total_return_pct"))),
                "gross_return_pct_before_costs": _pct(
                    _float(replay_result.get("gross_return_pct_before_costs"))
                ),
                "estimated_cost_drag_pct": _pct(_float(replay_result.get("estimated_cost_drag_pct"))),
                "max_drawdown_pct": _pct(_float(replay_result.get("max_drawdown_pct"))),
                "min_equity": replay_result.get("min_equity"),
                "trade_like_events": int(replay_result.get("trade_like_events") or 0),
                "avg_abs_account_exposure": replay_result.get("avg_abs_account_exposure"),
                "max_abs_account_exposure": replay_result.get("max_abs_account_exposure"),
                "event_counts": replay_result.get("event_counts") or {},
                "event_structure": _fold_event_structure(replay_result),
                "alpha_actionability": _fold_alpha_actionability(replay_result),
                "sample_events": list(replay_result.get("sample_events") or []),
                "cost_diagnostics": dict(replay_result.get("cost_diagnostics") or {}),
                "regime_performance": dict(replay_result.get("regime_performance") or {}),
                "window_meta": meta,
            }
        payload["summary"]["replay_selected_oos"] = _replay_summary(rows)
    return replay_summary


def _replay_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    replays = [
        dict(row.get("replay_selected_oos") or {})
        for row in rows
        if dict(row.get("replay_selected_oos") or {}).get("status") == "ok"
    ]
    if not replays:
        return {
            "enabled": True,
            "fold_count": 0,
            "status": "no_replays",
        }
    returns = [_float(item.get("return_pct")) for item in replays]
    drawdowns = [_float(item.get("max_drawdown_pct")) for item in replays]
    equity = 1.0
    for value in returns:
        equity *= _safe_equity(value)
    max_dd = max(drawdowns) if drawdowns else 0.0
    if max_dd <= 20.0:
        drawdown_verdict = "pass"
    elif max_dd <= 35.0:
        drawdown_verdict = "watch"
    else:
        drawdown_verdict = "fail"
    if min(returns) >= 5.0 and all(value > 0.0 for value in returns):
        return_verdict = "pass"
    elif all(value > 0.0 for value in returns):
        return_verdict = "watch"
    else:
        return_verdict = "fail"
    verdict = "fail" if "fail" in {return_verdict, drawdown_verdict} else "watch" if "watch" in {return_verdict, drawdown_verdict} else "pass"
    return {
        "enabled": True,
        "fold_count": len(replays),
        "compounded_return_pct": _pct((equity - 1.0) * 100.0),
        "avg_return_pct": _pct(mean(returns)),
        "min_return_pct": _pct(min(returns)),
        "max_drawdown_pct": _pct(max_dd),
        "return_verdict": return_verdict,
        "drawdown_verdict": drawdown_verdict,
        "verdict": verdict,
        "highest_drawdown_folds": sorted(
            [
                {
                    "fold": int(row.get("fold") or 0),
                    "return_pct": dict(row.get("replay_selected_oos") or {}).get("return_pct"),
                    "max_drawdown_pct": dict(row.get("replay_selected_oos") or {}).get(
                        "max_drawdown_pct"
                    ),
                    "trade_like_events": dict(row.get("replay_selected_oos") or {}).get(
                        "trade_like_events"
                    ),
                }
                for row in rows
                if dict(row.get("replay_selected_oos") or {}).get("status") == "ok"
            ],
            key=lambda item: -_float(item.get("max_drawdown_pct")),
        )[:5],
    }


def _is_protected_alpha_row(row: dict[str, Any]) -> bool:
    tags = set(row.get("tradeoff_tags") or [])
    if "high_cost_high_alpha_engine" in tags:
        return True
    return "alpha_engine_high_return" in tags and _float(row.get("stressed_return_pct")) >= 50.0


def _is_remediation_priority_row(row: dict[str, Any]) -> bool:
    tags = set(row.get("tradeoff_tags") or [])
    if "high_cost_high_alpha_engine" in tags:
        return False
    return (
        _float(row.get("stressed_return_pct")) <= 5.0
        or _float(row.get("breakeven_cost_multiplier"), 999.0) < 3.25
        or _float(row.get("cost_to_gross_ratio")) >= 0.30
        or (
            _float(row.get("drawdown_proxy_pct")) >= 35.0
            and "dd_proxy_from_cost_stress_not_return_failure" not in tags
        )
    )


def _scenario_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    equity = 1.0
    returns: list[float] = []
    drawdowns: list[float] = []
    cost_drags: list[float] = []
    carry_drags: list[float] = []
    cost_to_gross_ratios: list[float] = []
    floor_gaps: list[float] = []
    root_cause_counts: dict[str, int] = {}
    tradeoff_tag_counts: dict[str, int] = {}
    remediation_hint_counts: dict[str, int] = {}
    for row in rows:
        ret = _float(row.get("stressed_return_pct"))
        returns.append(ret)
        drawdowns.append(_float(row.get("drawdown_proxy_pct")))
        cost_drags.append(_float(row.get("baseline_cost_drag_pct")) * _float(row.get("trade_cost_multiplier"), 1.0))
        carry_drags.append(_float(row.get("carry_drag_pct")))
        if row.get("cost_to_gross_ratio") is not None:
            cost_to_gross_ratios.append(_float(row.get("cost_to_gross_ratio")))
        floor = dict(row.get("stress_floor") or {})
        floor_gaps.append(max(_float(floor.get("gross_return_gain_needed_pct")), 0.0))
        for cause in row.get("root_causes") or []:
            root_cause_counts[str(cause)] = root_cause_counts.get(str(cause), 0) + 1
        for tag in row.get("tradeoff_tags") or []:
            tradeoff_tag_counts[str(tag)] = tradeoff_tag_counts.get(str(tag), 0) + 1
        for hint in row.get("remediation_hints") or []:
            remediation_hint_counts[str(hint)] = remediation_hint_counts.get(str(hint), 0) + 1
        equity *= _safe_equity(ret)
    positive = sum(1 for value in returns if value > 0.0)
    min_return = min(returns) if returns else 0.0
    max_dd = max(drawdowns) if drawdowns else 0.0
    if positive == len(returns) and min_return >= 5.0:
        return_verdict = "pass"
    elif positive == len(returns) and min_return > 0.0:
        return_verdict = "watch"
    else:
        return_verdict = "fail"
    if max_dd <= 20.0:
        drawdown_verdict = "pass"
    elif max_dd <= 35.0:
        drawdown_verdict = "watch"
    else:
        drawdown_verdict = "fail"
    protected_alpha_folds = [row for row in rows if _is_protected_alpha_row(row)]
    actionable_drawdown_rows = [row for row in rows if not _is_protected_alpha_row(row)]
    actionable_drawdowns = [
        _float(row.get("drawdown_proxy_pct")) for row in actionable_drawdown_rows
    ]
    max_actionable_dd = max(actionable_drawdowns) if actionable_drawdowns else 0.0
    if max_actionable_dd <= 20.0:
        actionable_drawdown_verdict = "pass"
    elif max_actionable_dd <= 35.0:
        actionable_drawdown_verdict = "watch"
    else:
        actionable_drawdown_verdict = "fail"
    if return_verdict == "fail" or actionable_drawdown_verdict == "fail":
        verdict = "fail"
    elif (
        return_verdict == "watch"
        or actionable_drawdown_verdict == "watch"
        or drawdown_verdict in {"watch", "fail"}
    ):
        verdict = "watch"
    else:
        verdict = "pass"
    remediation_priority_folds = [row for row in rows if _is_remediation_priority_row(row)]
    stress_floor_priority_folds = [
        row
        for row in remediation_priority_folds
        if _float(dict(row.get("stress_floor") or {}).get("gross_return_gain_needed_pct")) > 0.0
    ]
    targeted_plan_resolved_folds = [
        row
        for row in stress_floor_priority_folds
        if dict(row.get("targeted_cost_reduction_plan") or {}).get("target_reached") is True
    ]
    targeted_plan_unresolved_folds = [
        row
        for row in stress_floor_priority_folds
        if dict(row.get("targeted_cost_reduction_plan") or {}).get("target_reached") is not True
    ]
    return {
        "fold_count": len(rows),
        "compounded_return_pct": _pct((equity - 1.0) * 100.0),
        "avg_return_pct": _pct(mean(returns)) if returns else 0.0,
        "min_return_pct": _pct(min_return),
        "max_return_pct": _pct(max(returns)) if returns else 0.0,
        "positive_fold_count": positive,
        "max_drawdown_proxy_pct": _pct(max_dd),
        "max_actionable_drawdown_proxy_pct": _pct(max_actionable_dd),
        "actionable_drawdown_verdict": actionable_drawdown_verdict,
        "protected_alpha_fold_count": len(protected_alpha_folds),
        "max_protected_alpha_drawdown_proxy_pct": (
            _pct(max(_float(row.get("drawdown_proxy_pct")) for row in protected_alpha_folds))
            if protected_alpha_folds
            else 0.0
        ),
        "avg_trade_cost_drag_pct": _pct(mean(cost_drags)) if cost_drags else 0.0,
        "avg_carry_drag_pct": _pct(mean(carry_drags)) if carry_drags else 0.0,
        "avg_cost_to_gross_ratio": round(mean(cost_to_gross_ratios), 4)
        if cost_to_gross_ratios
        else None,
        "stress_floor_gap_count": sum(1 for value in floor_gaps if value > 0.0),
        "max_stress_floor_gap_pct": _pct(max(floor_gaps)) if floor_gaps else 0.0,
        "avg_stress_floor_gap_pct": _pct(mean(floor_gaps)) if floor_gaps else 0.0,
        "targeted_plan_resolved_floor_gap_count": len(targeted_plan_resolved_folds),
        "targeted_plan_unresolved_floor_gap_count": len(targeted_plan_unresolved_folds),
        "root_cause_counts": dict(
            sorted(root_cause_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "tradeoff_tag_counts": dict(
            sorted(tradeoff_tag_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "remediation_hint_counts": dict(
            sorted(remediation_hint_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "return_verdict": return_verdict,
        "drawdown_verdict": drawdown_verdict,
        "verdict": verdict,
        "fragile_folds": sorted(
            rows,
            key=lambda item: (
                _float(item.get("stressed_return_pct")),
                -_float(item.get("drawdown_proxy_pct")),
            ),
        )[:5],
        "drawdown_fragile_folds": sorted(
            rows,
            key=lambda item: (
                -_float(item.get("drawdown_proxy_pct")),
                _float(item.get("stressed_return_pct")),
            ),
        )[:5],
        "actionable_drawdown_fragile_folds": sorted(
            actionable_drawdown_rows,
            key=lambda item: (
                -_float(item.get("drawdown_proxy_pct")),
                _float(item.get("stressed_return_pct")),
            ),
        )[:5],
        "cost_fragile_folds": sorted(
            rows,
            key=lambda item: (
                -_float(item.get("baseline_cost_drag_pct")),
                _float(item.get("breakeven_cost_multiplier"), 999.0),
            ),
        )[:5],
        "protected_alpha_folds": sorted(
            protected_alpha_folds,
            key=lambda item: (
                -_float(item.get("drawdown_proxy_pct")),
                -_float(item.get("stressed_return_pct")),
            ),
        )[:5],
        "remediation_priority_folds": sorted(
            remediation_priority_folds,
            key=lambda item: (
                -_float(dict(item.get("stress_floor") or {}).get("gross_return_gain_needed_pct")),
                _float(item.get("stressed_return_pct")),
                -_float(item.get("drawdown_proxy_pct")),
            ),
        )[:5],
        "targeted_plan_unresolved_folds": sorted(
            targeted_plan_unresolved_folds,
            key=lambda item: (
                -_float(dict(item.get("stress_floor") or {}).get("gross_return_gain_needed_pct")),
                _float(item.get("stressed_return_pct")),
            ),
        )[:5],
    }


def build_stress_report(
    source_report: dict[str, Any],
    *,
    scenarios: list[StressScenario] | None = None,
    input_report_path: str | None = None,
    replay_selected_folds: bool = False,
    replay_cache_dir: str | None = None,
    replay_base_url: str | None = None,
    replay_load_days: int | None = None,
    replay_min_periods: int = 200,
    replay_sleep_seconds: float = 0.0,
) -> dict[str, Any]:
    cost_model = dict(source_report.get("cost_model") or {})
    base_cost_bps_per_side = max(
        _float(cost_model.get("fee_bps_per_side")) + _float(cost_model.get("slippage_bps_per_side")),
        0.0,
    )
    scenario_list = scenarios or _default_scenarios(base_cost_bps_per_side)
    folds = [dict(item or {}) for item in source_report.get("folds") or []]
    scenario_payload: dict[str, Any] = {}
    for scenario in scenario_list:
        rows = [
            _stress_fold(
                fold,
                scenario,
                base_cost_bps_per_side=base_cost_bps_per_side,
            )
            for fold in folds
            if fold.get("test_result")
        ]
        scenario_payload[scenario.name] = {
            "scenario": {
                "name": scenario.name,
                "fee_bps_per_side": scenario.fee_bps_per_side,
                "slippage_bps_per_side": scenario.slippage_bps_per_side,
                "trade_cost_multiplier": _scenario_cost_multiplier(
                    scenario,
                    base_cost_bps_per_side=base_cost_bps_per_side,
                ),
                "funding_bps_per_8h": scenario.funding_bps_per_8h,
                "borrow_bps_per_day": scenario.borrow_bps_per_day,
            },
            "summary": _scenario_summary(rows),
            "folds": rows,
        }
    replay_summary = None
    if replay_selected_folds:
        replay_summary = _attach_replayed_selected_oos_metrics(
            scenario_payload,
            source_report,
            scenario_list=scenario_list,
            base_cost_bps_per_side=base_cost_bps_per_side,
            cache_dir=replay_cache_dir,
            base_url=replay_base_url,
            load_days=replay_load_days,
            min_periods=int(replay_min_periods),
            sleep_seconds=float(replay_sleep_seconds),
        )
    baseline = scenario_payload.get("baseline", {})
    non_baseline = [
        payload
        for name, payload in scenario_payload.items()
        if name != "baseline"
    ]
    worst = min(
        non_baseline or list(scenario_payload.values()),
        key=lambda payload: _float(dict(payload.get("summary") or {}).get("compounded_return_pct")),
    )
    breakevens = [
        _float(row.get("breakeven_cost_multiplier"))
        for payload in scenario_payload.values()
        for row in payload.get("folds") or []
        if row.get("breakeven_cost_multiplier") is not None
    ]
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "input_report": input_report_path,
        "source_report": source_report.get("source_report"),
        "source_created_at": source_report.get("created_at"),
        "symbol": source_report.get("symbol"),
        "exec_interval": source_report.get("exec_interval"),
        "method": "selected_oos_gross_minus_scaled_cost_proxy",
        "method_notes": [
            "uses stored selected OOS fold gross_return_pct_before_costs and estimated_cost_drag_pct",
            "does not reselect candidates or replay order timing",
            "drawdown_proxy adds extra modeled drag to reported fold drawdown as a conservative first-pass bound",
            "funding/borrow drag is approximated from avg_abs_account_exposure and fold years",
        ],
        "base_cost_bps_per_side": base_cost_bps_per_side,
        "baseline_summary": baseline.get("summary") or {},
        "worst_stress_summary": worst.get("summary") or {},
        "min_breakeven_cost_multiplier": round(min(breakevens), 4) if breakevens else None,
        "replay_selected_oos": replay_summary
        or {
            "enabled": False,
            "method": "not_requested",
        },
        "scenarios": scenario_payload,
    }


def _format_top_cost_reasons(row: dict[str, Any]) -> str:
    parts = []
    for item in row.get("top_cost_reasons") or []:
        if not isinstance(item, dict):
            continue
        parts.append(f"{item.get('name')}={item.get('value')}")
    return ", ".join(parts)


def _format_root_causes(row: dict[str, Any]) -> str:
    return ", ".join(str(item) for item in row.get("root_causes") or [])


def _format_tradeoff_tags(row: dict[str, Any]) -> str:
    return ", ".join(str(item) for item in row.get("tradeoff_tags") or [])


def _format_remediation_hints(row: dict[str, Any]) -> str:
    return ", ".join(str(item) for item in row.get("remediation_hints") or [])


def _format_targeted_plan_steps(row: dict[str, Any]) -> str:
    plan = dict(row.get("targeted_cost_reduction_plan") or {})
    steps = []
    for item in list(plan.get("steps") or [])[:3]:
        if not isinstance(item, dict):
            continue
        steps.append(
            f"{item.get('reason')} cut={item.get('planned_baseline_cost_cut_pct')} "
            f"share={item.get('planned_cut_share_of_reason')}"
        )
    return ", ".join(steps)


def _stress_floor_value(row: dict[str, Any], key: str) -> Any:
    return dict(row.get("stress_floor") or {}).get(key)


def _markdown_table(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Current-System Stress",
        "",
        f"- Created at: `{report.get('created_at')}`",
        f"- Symbol: `{report.get('symbol')}`",
        f"- Exec interval: `{report.get('exec_interval')}`",
        f"- Method: `{report.get('method')}`",
        f"- Base per-side fee+slippage bps: `{report.get('base_cost_bps_per_side')}`",
        f"- Min fold breakeven cost multiplier: `{report.get('min_breakeven_cost_multiplier')}`",
        "",
        "## Scenario Summary",
        "",
        "| Scenario | Compounded % | Avg % | Min % | Positive | Max DD proxy % | Actionable DD proxy % | Protected alpha folds | Floor gaps | Max floor gap % | Avg cost % | Avg carry % | Return | DD | Actionable DD | Overall |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for name, payload in report.get("scenarios", {}).items():
        summary = dict(payload.get("summary") or {})
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(summary.get("compounded_return_pct")),
                    str(summary.get("avg_return_pct")),
                    str(summary.get("min_return_pct")),
                    f"{summary.get('positive_fold_count')}/{summary.get('fold_count')}",
                    str(summary.get("max_drawdown_proxy_pct")),
                    str(summary.get("max_actionable_drawdown_proxy_pct")),
                    str(summary.get("protected_alpha_fold_count")),
                    str(summary.get("stress_floor_gap_count")),
                    str(summary.get("max_stress_floor_gap_pct")),
                    str(summary.get("avg_trade_cost_drag_pct")),
                    str(summary.get("avg_carry_drag_pct")),
                    str(summary.get("return_verdict")),
                    str(summary.get("drawdown_verdict")),
                    str(summary.get("actionable_drawdown_verdict")),
                    str(summary.get("verdict")),
                ]
            )
            + " |"
        )
    replay = dict(report.get("replay_selected_oos") or {})
    if replay.get("enabled"):
        lines.extend(
            [
                "",
                "## Selected OOS Replay Summary",
                "",
                (
                    f"- Method: `{replay.get('method')}`; load_days=`{replay.get('load_days')}`; "
                    f"failures=`{replay.get('failed_replay_count')}`"
                ),
                "",
                "| Scenario | Compounded % | Avg % | Min % | Max replay DD % | Return | DD | Overall |",
                "| --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
            ]
        )
        for name, payload in report.get("scenarios", {}).items():
            replay_summary = dict(dict(payload.get("summary") or {}).get("replay_selected_oos") or {})
            if not replay_summary or replay_summary.get("status") == "no_replays":
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(name),
                        str(replay_summary.get("compounded_return_pct")),
                        str(replay_summary.get("avg_return_pct")),
                        str(replay_summary.get("min_return_pct")),
                        str(replay_summary.get("max_drawdown_pct")),
                        str(replay_summary.get("return_verdict")),
                        str(replay_summary.get("drawdown_verdict")),
                        str(replay_summary.get("verdict")),
                    ]
                )
                + " |"
            )
    lines.extend(["", "## Root Cause Counts", ""])
    for name, payload in report.get("scenarios", {}).items():
        summary = dict(payload.get("summary") or {})
        counts = dict(summary.get("root_cause_counts") or {})
        if not counts:
            continue
        count_text = ", ".join(f"{key}={value}" for key, value in counts.items())
        lines.append(f"- `{name}`: {count_text}")
    lines.extend(["", "## Tradeoff Tag Counts", ""])
    for name, payload in report.get("scenarios", {}).items():
        summary = dict(payload.get("summary") or {})
        counts = dict(summary.get("tradeoff_tag_counts") or {})
        if not counts:
            continue
        count_text = ", ".join(f"{key}={value}" for key, value in counts.items())
        lines.append(f"- `{name}`: {count_text}")
    lines.extend(["", "## Remediation Hint Counts", ""])
    for name, payload in report.get("scenarios", {}).items():
        summary = dict(payload.get("summary") or {})
        counts = dict(summary.get("remediation_hint_counts") or {})
        if not counts:
            continue
        count_text = ", ".join(f"{key}={value}" for key, value in counts.items())
        lines.append(f"- `{name}`: {count_text}")
    lines.extend(["", "## Fragile Folds", ""])
    for name, payload in report.get("scenarios", {}).items():
        summary = dict(payload.get("summary") or {})
        fragile = list(summary.get("fragile_folds") or [])
        if not fragile:
            continue
        lines.extend(
            [
                f"### {name}",
                "",
                "| Fold | Return % | Floor buffer % | Need gross % | Need cost cut % | Delta % | DD proxy % | Carry % | Breakeven cost x | Cost/Gross | Root causes | Tradeoff tags | Hints | Top cost reasons |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
            ]
        )
        for row in fragile:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("fold")),
                        str(row.get("stressed_return_pct")),
                        str(_stress_floor_value(row, "stress_buffer_to_floor_pct")),
                        str(_stress_floor_value(row, "gross_return_gain_needed_pct")),
                        str(_stress_floor_value(row, "baseline_cost_reduction_needed_pct")),
                        str(row.get("return_delta_pct")),
                        str(row.get("drawdown_proxy_pct")),
                        str(row.get("carry_drag_pct")),
                        str(row.get("breakeven_cost_multiplier")),
                        str(row.get("cost_to_gross_ratio")),
                        _format_root_causes(row),
                        _format_tradeoff_tags(row),
                        _format_remediation_hints(row),
                        _format_top_cost_reasons(row),
                    ]
                )
                + " |"
            )
        lines.append("")
    lines.extend(["", "## Drawdown Fragile Folds", ""])
    for name, payload in report.get("scenarios", {}).items():
        summary = dict(payload.get("summary") or {})
        fragile = list(summary.get("drawdown_fragile_folds") or [])
        if not fragile:
            continue
        lines.extend(
            [
                f"### {name}",
                "",
                "| Fold | DD proxy % | Return % | Floor buffer % | Need gross % | Need cost cut % | Delta % | Cost % | Breakeven cost x | Root causes | Tradeoff tags | Hints | Top cost reasons |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
            ]
        )
        for row in fragile:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("fold")),
                        str(row.get("drawdown_proxy_pct")),
                        str(row.get("stressed_return_pct")),
                        str(_stress_floor_value(row, "stress_buffer_to_floor_pct")),
                        str(_stress_floor_value(row, "gross_return_gain_needed_pct")),
                        str(_stress_floor_value(row, "baseline_cost_reduction_needed_pct")),
                        str(row.get("return_delta_pct")),
                        str(row.get("baseline_cost_drag_pct")),
                        str(row.get("breakeven_cost_multiplier")),
                        _format_root_causes(row),
                        _format_tradeoff_tags(row),
                        _format_remediation_hints(row),
                        _format_top_cost_reasons(row),
                    ]
                )
                + " |"
            )
        lines.append("")
    lines.extend(["", "## Cost Fragile Folds", ""])
    for name, payload in report.get("scenarios", {}).items():
        summary = dict(payload.get("summary") or {})
        fragile = list(summary.get("cost_fragile_folds") or [])
        if not fragile:
            continue
        lines.extend(
            [
                f"### {name}",
                "",
                "| Fold | Cost % | Return % | Floor buffer % | Need gross % | Need cost cut % | DD proxy % | Breakeven cost x | Cost/Gross | Root causes | Tradeoff tags | Hints | Top cost reasons |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
            ]
        )
        for row in fragile:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("fold")),
                        str(row.get("baseline_cost_drag_pct")),
                        str(row.get("stressed_return_pct")),
                        str(_stress_floor_value(row, "stress_buffer_to_floor_pct")),
                        str(_stress_floor_value(row, "gross_return_gain_needed_pct")),
                        str(_stress_floor_value(row, "baseline_cost_reduction_needed_pct")),
                        str(row.get("drawdown_proxy_pct")),
                        str(row.get("breakeven_cost_multiplier")),
                        str(row.get("cost_to_gross_ratio")),
                        _format_root_causes(row),
                        _format_tradeoff_tags(row),
                        _format_remediation_hints(row),
                        _format_top_cost_reasons(row),
                    ]
                )
                + " |"
            )
        lines.append("")
    lines.extend(["", "## Protected Alpha Folds", ""])
    for name, payload in report.get("scenarios", {}).items():
        summary = dict(payload.get("summary") or {})
        folds = list(summary.get("protected_alpha_folds") or [])
        if not folds:
            continue
        lines.extend(
            [
                f"### {name}",
                "",
                "| Fold | Return % | Floor buffer % | DD proxy % | Cost % | Breakeven cost x | Tradeoff tags | Hints |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for row in folds:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("fold")),
                        str(row.get("stressed_return_pct")),
                        str(_stress_floor_value(row, "stress_buffer_to_floor_pct")),
                        str(row.get("drawdown_proxy_pct")),
                        str(row.get("baseline_cost_drag_pct")),
                        str(row.get("breakeven_cost_multiplier")),
                        _format_tradeoff_tags(row),
                        _format_remediation_hints(row),
                    ]
                )
                + " |"
            )
        lines.append("")
    lines.extend(["", "## Remediation Priority Folds", ""])
    for name, payload in report.get("scenarios", {}).items():
        summary = dict(payload.get("summary") or {})
        folds = list(summary.get("remediation_priority_folds") or [])
        if not folds:
            continue
        lines.extend(
            [
                f"### {name}",
                "",
                "| Fold | Return % | Floor buffer % | Need gross % | Need cost cut % | Planned cost cut % | Projected return % | Plan reaches | DD proxy % | Cost/Gross | Breakeven cost x | Root causes | Tradeoff tags | Hints | Plan steps |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | --- | --- | --- |",
            ]
        )
        for row in folds:
            plan = dict(row.get("targeted_cost_reduction_plan") or {})
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("fold")),
                        str(row.get("stressed_return_pct")),
                        str(_stress_floor_value(row, "stress_buffer_to_floor_pct")),
                        str(_stress_floor_value(row, "gross_return_gain_needed_pct")),
                        str(_stress_floor_value(row, "baseline_cost_reduction_needed_pct")),
                        str(plan.get("planned_baseline_cost_cut_pct")),
                        str(plan.get("projected_stressed_return_pct")),
                        str(plan.get("target_reached")),
                        str(row.get("drawdown_proxy_pct")),
                        str(row.get("cost_to_gross_ratio")),
                        str(row.get("breakeven_cost_multiplier")),
                        _format_root_causes(row),
                        _format_tradeoff_tags(row),
                        _format_remediation_hints(row),
                        _format_targeted_plan_steps(row),
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fast selected-model stress report for market-state rotation v6 walk-forward output."
    )
    parser.add_argument("--report", required=True, help="Walk-forward JSON report to stress.")
    parser.add_argument(
        "--report-dir",
        default="reports/validation/diagnostics/market_state_rotation_v6_stress_current_system",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        type=_parse_scenario,
        help=(
            "Optional scenario. Use name:cost_mult or "
            "name:fee_bps:slip_bps:funding_bps[:borrow_bps_day]. Can be repeated."
        ),
    )
    parser.add_argument(
        "--replay-selected-folds",
        action="store_true",
        help=(
            "Rerun each selected OOS fold with the stressed scenario cost/funding settings "
            "and attach realized replay return/DD metrics."
        ),
    )
    parser.add_argument(
        "--replay-cache-dir",
        default=None,
        help="Optional bar cache directory for --replay-selected-folds.",
    )
    parser.add_argument(
        "--replay-base-url",
        default=None,
        help="Optional Binance REST base URL for --replay-selected-folds.",
    )
    parser.add_argument(
        "--replay-load-days",
        type=int,
        default=None,
        help="Optional load-days override for --replay-selected-folds.",
    )
    parser.add_argument(
        "--replay-min-periods",
        type=int,
        default=200,
        help="Minimum bars required by the OOS replay.",
    )
    parser.add_argument(
        "--replay-sleep-seconds",
        type=float,
        default=0.0,
        help="Sleep between remote bar fetches during replay if cache misses.",
    )
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = ROOT_DIR / report_path
    source_report = json.loads(report_path.read_text())
    try:
        input_report_path = str(report_path.relative_to(ROOT_DIR))
    except ValueError:
        input_report_path = str(report_path)
    report = build_stress_report(
        source_report,
        scenarios=args.scenario,
        input_report_path=input_report_path,
        replay_selected_folds=bool(args.replay_selected_folds),
        replay_cache_dir=args.replay_cache_dir,
        replay_base_url=args.replay_base_url,
        replay_load_days=args.replay_load_days,
        replay_min_periods=int(args.replay_min_periods),
        replay_sleep_seconds=float(args.replay_sleep_seconds),
    )
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_current_system_stress.json"
        md_path = report_dir / "market_state_rotation_v6_current_system_stress.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        md_path.write_text(_markdown_table(report))
        print(f"wrote {json_path.relative_to(ROOT_DIR)}")
        print(f"wrote {md_path.relative_to(ROOT_DIR)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
