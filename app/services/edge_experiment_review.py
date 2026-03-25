from __future__ import annotations

from typing import Any

_EDGE_PROOF_GOAL_CLOSED_TRADES = 100


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _ratio(numerator: float, denominator: float) -> float:
    if abs(float(denominator)) <= 1e-9:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _bucket_rows(payload: dict[str, Any] | None, axis: str) -> dict[str, dict[str, Any]]:
    source = dict(payload or {})
    decomposition = dict(source.get("decomposition") or {})
    return {
        str(item.get("key") or ""): dict(item)
        for item in list(decomposition.get(axis) or [])
        if str(item.get("key") or "")
    }


def _bucket_summary(row: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(row or {})
    if not source:
        return {}

    submitted_expected_r = _float(source.get("submitted_expected_r", 0.0))
    filled_expected_r = _float(source.get("filled_expected_r", 0.0))
    closed_expected_r = _float(source.get("closed_expected_r", 0.0))
    post_cost_closed_r = _float(source.get("baseline_adjusted_r", 0.0))
    return {
        "key": str(source.get("key") or "unknown"),
        "submitted": _int(source.get("submitted", 0)),
        "filled": _int(source.get("filled", 0)),
        "closed": _int(source.get("closed", 0)),
        "submitted_expected_r": round(submitted_expected_r, 4),
        "filled_expected_r": round(filled_expected_r, 4),
        "closed_expected_r": round(closed_expected_r, 4),
        "post_cost_closed_realized_r": round(post_cost_closed_r, 4),
        "fill_rate_from_submitted": round(_float(source.get("fill_rate_from_submitted", 0.0)), 4),
        "capture_ratio_r": _ratio(filled_expected_r, submitted_expected_r),
        "true_edge_ratio": _ratio(post_cost_closed_r, closed_expected_r),
        "closed_post_cost_delta_r": round(post_cost_closed_r - closed_expected_r, 4),
    }


def _compare_variants(
    *,
    rows_by_key: dict[str, dict[str, Any]],
    lhs_key: str,
    rhs_key: str,
) -> dict[str, Any]:
    lhs = _bucket_summary(rows_by_key.get(lhs_key))
    rhs = _bucket_summary(rows_by_key.get(rhs_key))
    if not lhs and not rhs:
        return {
            "available": False,
            "comparison_ready": False,
            "reason": "no_bucket_coverage",
            "preferred_variant": "none",
            "recommendation_reason": "not_available",
            "lhs": {},
            "rhs": {},
        }
    if not lhs or not rhs:
        preferred = lhs.get("key") or rhs.get("key") or "none"
        return {
            "available": True,
            "comparison_ready": False,
            "reason": "insufficient_branch_coverage",
            "preferred_variant": preferred,
            "recommendation_reason": "only_one_branch_has_coverage",
            "lhs": lhs,
            "rhs": rhs,
        }

    lhs_true_edge = _float(lhs.get("true_edge_ratio", 0.0))
    rhs_true_edge = _float(rhs.get("true_edge_ratio", 0.0))
    lhs_capture = _float(lhs.get("capture_ratio_r", 0.0))
    rhs_capture = _float(rhs.get("capture_ratio_r", 0.0))
    lhs_fill_rate = _float(lhs.get("fill_rate_from_submitted", 0.0))
    rhs_fill_rate = _float(rhs.get("fill_rate_from_submitted", 0.0))
    lhs_closed = _int(lhs.get("closed", 0))
    rhs_closed = _int(rhs.get("closed", 0))

    preferred_variant = "none"
    recommendation_reason = "branches_are_balanced"
    if lhs_closed >= 2 and rhs_closed >= 2 and abs(lhs_true_edge - rhs_true_edge) >= 0.10:
        preferred_variant = lhs["key"] if lhs_true_edge > rhs_true_edge else rhs["key"]
        recommendation_reason = "higher_post_cost_true_edge_ratio"
    elif abs(lhs_capture - rhs_capture) >= 0.10:
        preferred_variant = lhs["key"] if lhs_capture > rhs_capture else rhs["key"]
        recommendation_reason = "better_fill_capture_ratio"
    elif abs(lhs_fill_rate - rhs_fill_rate) >= 0.10:
        preferred_variant = lhs["key"] if lhs_fill_rate > rhs_fill_rate else rhs["key"]
        recommendation_reason = "higher_fill_rate_from_submitted"
    elif abs(_float(lhs.get("post_cost_closed_realized_r", 0.0)) - _float(rhs.get("post_cost_closed_realized_r", 0.0))) >= 0.05:
        preferred_variant = (
            lhs["key"]
            if _float(lhs.get("post_cost_closed_realized_r", 0.0))
            > _float(rhs.get("post_cost_closed_realized_r", 0.0))
            else rhs["key"]
        )
        recommendation_reason = "higher_post_cost_closed_realized_r"

    return {
        "available": True,
        "comparison_ready": True,
        "reason": "ok",
        "preferred_variant": preferred_variant,
        "recommendation_reason": recommendation_reason,
        "lhs": lhs,
        "rhs": rhs,
        "capture_ratio_gap": round(lhs_capture - rhs_capture, 4),
        "true_edge_ratio_gap": round(lhs_true_edge - rhs_true_edge, 4),
        "fill_rate_gap": round(lhs_fill_rate - rhs_fill_rate, 4),
    }


def _sample_progress(*, closed_trade_count: int) -> dict[str, Any]:
    count = max(_int(closed_trade_count, 0), 0)
    milestones = [4, 6, 8, 20, 50, 100, 300]
    next_target = next((target for target in milestones if count < target), 0)

    if count < 4:
        maturity = "pre_directional"
    elif count < 6:
        maturity = "directional_only"
    elif count < 8:
        maturity = "review_ready"
    elif count < 20:
        maturity = "pilot_live"
    elif count < 50:
        maturity = "early_edge"
    elif count < 100:
        maturity = "emerging_edge"
    elif count < 300:
        maturity = "credible_edge"
    else:
        maturity = "validated_edge"

    return {
        "closed_trade_count": count,
        "sample_maturity_state": maturity,
        "directional_ready": bool(count >= 4),
        "decision_ready": bool(count >= 6),
        "promotion_ready": bool(count >= 8),
        "operator_sample_floor_ready": bool(count >= 20),
        "next_sample_target_closed_trades": int(next_target),
        "remaining_closed_trades_to_next_target": max(int(next_target) - count, 0) if next_target else 0,
        "edge_proof_goal_closed_trades": _EDGE_PROOF_GOAL_CLOSED_TRADES,
        "edge_proof_goal_ready": bool(count >= _EDGE_PROOF_GOAL_CLOSED_TRADES),
        "remaining_closed_trades_to_edge_proof_goal": max(_EDGE_PROOF_GOAL_CLOSED_TRADES - count, 0),
    }


def _edge_proof_posture(
    *,
    closed_trade_count: int,
    true_edge_ratio: float,
    edge_decay_rate: float,
    sample_progress: dict[str, Any],
    regime_edge_breakdown: dict[str, Any],
) -> dict[str, Any]:
    count = max(_int(closed_trade_count, 0), 0)
    proof_goal = _int(sample_progress.get("edge_proof_goal_closed_trades", _EDGE_PROOF_GOAL_CLOSED_TRADES))
    proof_goal_ready = bool(sample_progress.get("edge_proof_goal_ready", False))
    remaining_to_goal = max(_int(sample_progress.get("remaining_closed_trades_to_edge_proof_goal", 0)), 0)
    maturity = str(sample_progress.get("sample_maturity_state") or "unknown")
    regime_dependency_state = str(regime_edge_breakdown.get("dependency_state") or "not_available")

    posture_state = "sample_building"
    claim_state = "do_not_claim_edge_yet"
    focus = "accumulate_closed_trades"
    summary = (
        f"Closed sample is {count}/{proof_goal}; keep the system in research posture until the edge proof goal is met."
    )

    if proof_goal_ready and regime_dependency_state == "regime_dependent":
        posture_state = "regime_limited"
        claim_state = "regime_specific_only"
        focus = "close_weakest_regime_gap"
        summary = "Closed sample cleared the proof goal, but edge is still regime-dependent; do not generalize promotion."
    elif proof_goal_ready and (true_edge_ratio < 1.0 or edge_decay_rate <= -0.05):
        posture_state = "proof_goal_met_but_edge_weak"
        claim_state = "keep_research_only"
        focus = "monitor_true_edge_and_decay"
        summary = "Closed sample cleared the proof goal, but current true-edge/decay does not support a durable edge claim."
    elif proof_goal_ready:
        posture_state = "edge_claim_ready"
        claim_state = "eligible_for_edge_claim"
        focus = "review_promotion_cautiously"
        summary = "Closed sample cleared the proof goal and current edge metrics are strong enough to review as a durable candidate."
    elif maturity in {"pre_directional", "directional_only", "review_ready"}:
        focus = "accumulate_closed_trades_before_split_conclusions"
        summary = (
            f"Closed sample is {count}/{proof_goal}; treat split preferences as directional only until more closes accumulate."
        )

    return {
        "state": posture_state,
        "claim_state": claim_state,
        "focus": focus,
        "edge_proof_goal_closed_trades": proof_goal,
        "edge_proof_goal_ready": proof_goal_ready,
        "remaining_closed_trades_to_edge_proof_goal": remaining_to_goal,
        "summary": summary,
    }


def _operating_discipline(
    *,
    edge_proof_posture: dict[str, Any],
    sample_progress: dict[str, Any],
    regime_edge_breakdown: dict[str, Any],
) -> dict[str, Any]:
    posture_state = str(edge_proof_posture.get("state") or "sample_building")
    discipline_state = "research_only_until_edge_proof_goal"
    structure_change_review_allowed = False
    profit_claim_allowed = False
    proof_goal = _int(edge_proof_posture.get("edge_proof_goal_closed_trades", _EDGE_PROOF_GOAL_CLOSED_TRADES))
    closed_trade_count = _int(sample_progress.get("closed_trade_count", 0))
    regime_dependency_state = str(regime_edge_breakdown.get("dependency_state") or "not_available")
    framework_quality_state = "framework_ready"
    system_mode = "operate_and_experiment"
    evaluation_focus = "after_cost_edge_only"
    evaluation_metric = "true_edge_ratio_post_cost_closed"
    improvement_priority = "prove_single_edge_before_density_or_strategy_expansion"
    edge_status = "unknown_until_after_cost_proof"
    early_loss_rewrite_embargo_closed_trades = 50
    early_loss_rewrite_embargo_active = closed_trade_count < early_loss_rewrite_embargo_closed_trades
    regime_stability_required_for_expansion = True
    rollout_expansion_allowed = False
    loss_driven_rewrite_allowed = False
    signal_density_control_review_allowed = False
    multi_strategy_expansion_review_allowed = False
    summary = (
        "Framework is ready, but edge is still unproven; operate and experiment with one active split, and judge the "
        "system on after-cost closed-trade edge instead of structure changes until the proof goal is met. Keep signal-density "
        "tuning and multi-strategy expansion deferred until one edge is actually proven."
    )

    if posture_state == "regime_limited":
        discipline_state = "research_only_until_regime_confirms"
        edge_status = "unknown_until_regime_confirms"
        summary = (
            "Framework is ready, but edge is still regime-limited; keep one experiment active and judge progress on "
            "after-cost closed-trade edge until weaker regimes confirm. Do not expand rollout, tune signal density, or open "
            "multi-strategy expansion until regime stability is real."
        )
    elif posture_state == "proof_goal_met_but_edge_weak":
        discipline_state = "research_only_until_edge_stabilizes"
        edge_status = "unknown_until_edge_stabilizes"
        summary = (
            "The proof goal is met, but after-cost edge quality is still weak; do not claim profitability or justify "
            "structural rewrites, signal-density tuning, or expansion from this sample yet."
        )
    elif posture_state == "edge_claim_ready":
        discipline_state = "reviewable_after_edge_proof"
        structure_change_review_allowed = True
        profit_claim_allowed = True
        edge_status = "reviewable_after_cost_edge"
        rollout_expansion_allowed = regime_dependency_state == "stable_across_regimes"
        loss_driven_rewrite_allowed = not early_loss_rewrite_embargo_active
        signal_density_control_review_allowed = rollout_expansion_allowed
        multi_strategy_expansion_review_allowed = rollout_expansion_allowed
        summary = (
            "After-cost edge evidence is finally strong enough for cautious review; keep single-experiment discipline "
            "and treat any structural change as reviewable, not guaranteed profit."
        )
        if not rollout_expansion_allowed:
            summary += " Expansion still stays blocked until regime stability is confirmed."

    if posture_state != "edge_claim_ready":
        loss_driven_rewrite_allowed = False
        signal_density_control_review_allowed = False
        multi_strategy_expansion_review_allowed = False

    deferred_review_backlog: list[str] = []
    if not signal_density_control_review_allowed:
        deferred_review_backlog.append("signal_density_control")
    if not multi_strategy_expansion_review_allowed:
        deferred_review_backlog.append("multi_strategy_expansion")

    return {
        "discipline_state": discipline_state,
        "framework_quality_state": framework_quality_state,
        "system_mode": system_mode,
        "primary_goal": "find_first_verified_edge",
        "evaluation_focus": evaluation_focus,
        "evaluation_metric": evaluation_metric,
        "improvement_priority": improvement_priority,
        "minimum_closed_trades_for_edge_evaluation": proof_goal,
        "edge_status": edge_status,
        "single_experiment_only": True,
        "parallel_experiments_allowed": False,
        "profit_claim_allowed": profit_claim_allowed,
        "structure_change_review_allowed": structure_change_review_allowed,
        "early_loss_rewrite_embargo_closed_trades": early_loss_rewrite_embargo_closed_trades,
        "early_loss_rewrite_embargo_active": early_loss_rewrite_embargo_active,
        "loss_driven_rewrite_allowed": loss_driven_rewrite_allowed,
        "regime_stability_required_for_expansion": regime_stability_required_for_expansion,
        "rollout_expansion_allowed": rollout_expansion_allowed,
        "signal_density_control_review_allowed": signal_density_control_review_allowed,
        "multi_strategy_expansion_review_allowed": multi_strategy_expansion_review_allowed,
        "deferred_review_backlog": deferred_review_backlog,
        "summary": summary,
    }


def _experiment_sequence(
    *,
    entry_timing: dict[str, Any],
    execution_style: dict[str, Any],
    sample_progress: dict[str, Any],
) -> dict[str, Any]:
    decision_ready = bool(sample_progress.get("decision_ready", False))
    promotion_ready = bool(sample_progress.get("promotion_ready", False))
    entry_preferred = str(entry_timing.get("preferred_variant") or "none")
    execution_preferred = str(execution_style.get("preferred_variant") or "none")
    entry_timing_locked = bool(entry_timing.get("comparison_ready", False)) and decision_ready and entry_preferred not in {
        "",
        "none",
    }
    execution_style_locked = bool(execution_style.get("comparison_ready", False)) and decision_ready and execution_preferred not in {
        "",
        "none",
    }

    state = "entry_timing_first"
    current_priority_experiment = "entry_timing"
    current_priority_action = "run_entry_timing_split_review"
    summary = (
        "Lock entry timing first: compare early_limit versus reaction_confirmed before changing execution style or "
        "reviewing exit optimization."
    )

    if entry_timing_locked and not execution_style_locked:
        state = "execution_style_second"
        current_priority_experiment = "execution_style"
        current_priority_action = "run_execution_style_split_review"
        summary = (
            "Entry timing is directionally locked; lock execution style next by comparing passive_limit versus market "
            "before reviewing exit optimization."
        )
    elif entry_timing_locked and execution_style_locked and not promotion_ready:
        state = "sample_building_before_exit_optimization"
        current_priority_experiment = "sample_building"
        current_priority_action = "accumulate_closed_trades"
        summary = (
            "Entry timing and execution style both have directional coverage, but the closed-trade sample is still "
            "below the exit-review floor; accumulate more closes before exit optimization."
        )
    elif entry_timing_locked and execution_style_locked and promotion_ready:
        state = "exit_optimization_allowed"
        current_priority_experiment = "exit_optimization"
        current_priority_action = "run_shadow_exit_timing_review"
        summary = (
            "Entry timing and execution style are both locked with enough closed-trade evidence; exit optimization "
            "review can start without coupling it to the current split decision."
        )

    return {
        "state": state,
        "entry_timing_variants": ["early_limit", "reaction_confirmed"],
        "execution_style_variants": ["passive_limit", "market"],
        "entry_timing_locked": entry_timing_locked,
        "execution_style_locked": execution_style_locked,
        "exit_review_floor_closed_trades": 8,
        "exit_optimization_allowed": bool(entry_timing_locked and execution_style_locked and promotion_ready),
        "current_priority_experiment": current_priority_experiment,
        "current_priority_action": current_priority_action,
        "summary": summary,
    }


def _regime_edge_breakdown(payload: dict[str, Any] | None) -> dict[str, Any]:
    rows = [_bucket_summary(row) for row in list(_bucket_rows(payload, "regime").values())]
    rows = [row for row in rows if row]
    if not rows:
        return {
            "available": False,
            "dependency_state": "not_available",
            "dependency_gap": 0.0,
            "dominant_regime": {},
            "strongest_regime": {},
            "weakest_regime": {},
            "rows": [],
        }

    sorted_rows = sorted(
        rows,
        key=lambda item: (
            -_int(item.get("closed", 0)),
            -_int(item.get("filled", 0)),
            -_int(item.get("submitted", 0)),
            str(item.get("key") or ""),
        ),
    )
    dominant_regime = dict(sorted_rows[0] if sorted_rows else {})
    closed_rows = [row for row in sorted_rows if _int(row.get("closed", 0)) > 0]
    if not closed_rows:
        return {
            "available": True,
            "dependency_state": "insufficient_regime_closes",
            "dependency_gap": 0.0,
            "dominant_regime": dominant_regime,
            "strongest_regime": {},
            "weakest_regime": {},
            "rows": sorted_rows,
        }

    strongest_regime = dict(
        max(
            closed_rows,
            key=lambda item: (
                _float(item.get("true_edge_ratio", 0.0)),
                _int(item.get("closed", 0)),
                str(item.get("key") or ""),
            ),
        )
    )
    weakest_regime = dict(
        min(
            closed_rows,
            key=lambda item: (
                _float(item.get("true_edge_ratio", 0.0)),
                -_int(item.get("closed", 0)),
                str(item.get("key") or ""),
            ),
        )
    )
    dependency_gap = round(
        _float(strongest_regime.get("true_edge_ratio", 0.0))
        - _float(weakest_regime.get("true_edge_ratio", 0.0)),
        4,
    )
    if len(closed_rows) >= 2 and dependency_gap >= 0.20:
        dependency_state = "regime_dependent"
    elif len(closed_rows) >= 2:
        dependency_state = "stable_across_regimes"
    else:
        dependency_state = "single_regime_observed"

    return {
        "available": True,
        "dependency_state": dependency_state,
        "dependency_gap": dependency_gap,
        "dominant_regime": dominant_regime,
        "strongest_regime": strongest_regime,
        "weakest_regime": weakest_regime,
        "rows": sorted_rows,
    }


def build_edge_experiment_review(
    *,
    score_to_outcome_funnel: dict[str, Any] | None,
) -> dict[str, Any] | None:
    funnel_payload = dict(score_to_outcome_funnel or {})
    money_funnel = dict(funnel_payload.get("money_funnel") or {})
    if not money_funnel:
        return None

    historical_expected = dict(money_funnel.get("historical_expected_r") or {})
    historical_realized = dict(money_funnel.get("historical_realized_r") or {})
    historical_windows = dict(money_funnel.get("historical_windows") or {})
    history = dict(funnel_payload.get("historical_execution_outcomes") or {})
    if not history:
        history = {
            "closed": _int(funnel_payload.get("closed", 0)),
            "submitted": _int(funnel_payload.get("submitted", 0)),
            "filled": _int(funnel_payload.get("filled", 0)),
        }

    closed_expected_r = round(_float(historical_expected.get("closed", 0.0)), 4)
    post_cost_closed_realized_r = round(_float(historical_realized.get("post_cost_closed", 0.0)), 4)
    true_edge_ratio = _ratio(post_cost_closed_realized_r, closed_expected_r)
    recent_window = dict(historical_windows.get("recent") or {})
    prior_window = dict(historical_windows.get("prior") or {})
    recent_true_edge_ratio = round(_float(recent_window.get("true_edge_ratio", 0.0)), 4)
    prior_true_edge_ratio = round(_float(prior_window.get("true_edge_ratio", 0.0)), 4)
    recent_closed = _int(recent_window.get("closed", 0))
    prior_closed = _int(prior_window.get("closed", 0))
    if recent_closed > 0 and prior_closed > 0:
        edge_decay_rate = round(recent_true_edge_ratio - prior_true_edge_ratio, 4)
        edge_stability = round(abs(edge_decay_rate), 4)
    else:
        edge_decay_rate = 0.0
        edge_stability = 0.0

    if _int(history.get("closed", 0)) < 4:
        edge_state = "insufficient_edge_measurement"
    elif true_edge_ratio < 0.75 or edge_decay_rate <= -0.20:
        edge_state = "fragile_edge"
    elif true_edge_ratio < 1.0 or edge_decay_rate <= -0.10 or edge_stability >= 0.20:
        edge_state = "watch_edge"
    else:
        edge_state = "healthy_edge"

    if edge_state == "fragile_edge":
        summary = "Post-cost true edge is fragile; run controlled entry/execution experiments before changing strategy scope."
    elif edge_state == "watch_edge":
        summary = "Post-cost true edge is positive but unstable; prefer controlled split tests over structural rewrites."
    elif edge_state == "healthy_edge":
        summary = "Post-cost true edge is holding up across the current window; focus on controlled execution refinements."
    else:
        summary = "True-edge evidence is still thin; treat experiment output as directional until more closed trades accumulate."

    entry_timing = _compare_variants(
        rows_by_key=_bucket_rows(funnel_payload, "entry_timing_variant"),
        lhs_key="early_limit",
        rhs_key="reaction_confirmed",
    )
    execution_style = _compare_variants(
        rows_by_key=_bucket_rows(funnel_payload, "execution_style"),
        lhs_key="passive_limit",
        rhs_key="market",
    )
    sample_progress = _sample_progress(closed_trade_count=_int(history.get("closed", 0)))
    regime_edge_breakdown = _regime_edge_breakdown(funnel_payload)

    if str(regime_edge_breakdown.get("dependency_state") or "") == "regime_dependent":
        strongest_regime = dict(regime_edge_breakdown.get("strongest_regime") or {})
        weakest_regime = dict(regime_edge_breakdown.get("weakest_regime") or {})
        strongest_label = str(strongest_regime.get("key") or "unknown")
        weakest_label = str(weakest_regime.get("key") or "unknown")
        summary = (
            f"{summary} Regime dispersion is still meaningful; strongest={strongest_label}, "
            f"weakest={weakest_label}, so avoid generalizing the edge across regimes yet."
        )

    reason_codes = _dedupe(
        [
            f"edge_state:{edge_state}",
            f"true_edge_ratio:{true_edge_ratio:.4f}",
            f"entry_timing:{entry_timing.get('recommendation_reason', 'not_available')}",
            f"execution_style:{execution_style.get('recommendation_reason', 'not_available')}",
            f"sample_maturity:{sample_progress.get('sample_maturity_state', 'unknown')}",
            f"regime_dependency:{regime_edge_breakdown.get('dependency_state', 'not_available')}",
        ]
    )

    return {
        "available": True,
        "advisory_only": True,
        "edge_state": edge_state,
        "summary": summary,
        "reason_codes": reason_codes,
        "true_edge": {
            "closed_trade_count": _int(history.get("closed", 0)),
            "true_edge_ratio": true_edge_ratio,
            "recent_true_edge_ratio": recent_true_edge_ratio,
            "prior_true_edge_ratio": prior_true_edge_ratio,
            "edge_decay_rate": edge_decay_rate,
            "edge_stability": edge_stability,
            "closed_expected_r": closed_expected_r,
            "post_cost_closed_realized_r": post_cost_closed_realized_r,
            "recent_window": recent_window,
            "prior_window": prior_window,
        },
        "entry_timing_experiment": entry_timing,
        "execution_style_experiment": execution_style,
        "sample_progress": sample_progress,
        "regime_edge_breakdown": regime_edge_breakdown,
        "source_summary": {
            "money_funnel_summary": str(money_funnel.get("summary") or ""),
            "recent_window_closed": recent_closed,
            "prior_window_closed": prior_closed,
            "entry_timing_preferred_variant": entry_timing.get("preferred_variant", "none"),
            "execution_style_preferred_variant": execution_style.get("preferred_variant", "none"),
            "sample_maturity_state": str(sample_progress.get("sample_maturity_state") or "unknown"),
            "next_sample_target_closed_trades": int(sample_progress.get("next_sample_target_closed_trades", 0) or 0),
            "regime_dependency_state": str(regime_edge_breakdown.get("dependency_state") or "not_available"),
            "strongest_regime": str(dict(regime_edge_breakdown.get("strongest_regime") or {}).get("key") or "none"),
            "weakest_regime": str(dict(regime_edge_breakdown.get("weakest_regime") or {}).get("key") or "none"),
        },
    }


def summarize_edge_experiment_review(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    source = dict(payload or {})
    if not source:
        return None

    true_edge = dict(source.get("true_edge") or {})
    entry_timing = dict(source.get("entry_timing_experiment") or {})
    execution_style = dict(source.get("execution_style_experiment") or {})
    sample_progress = dict(source.get("sample_progress") or {})
    regime_edge_breakdown = dict(source.get("regime_edge_breakdown") or {})
    strongest_regime = dict(regime_edge_breakdown.get("strongest_regime") or {})
    weakest_regime = dict(regime_edge_breakdown.get("weakest_regime") or {})
    dominant_regime = dict(regime_edge_breakdown.get("dominant_regime") or {})
    edge_proof_posture = _edge_proof_posture(
        closed_trade_count=_int(true_edge.get("closed_trade_count", 0)),
        true_edge_ratio=_float(true_edge.get("true_edge_ratio", 0.0)),
        edge_decay_rate=_float(true_edge.get("edge_decay_rate", 0.0)),
        sample_progress=sample_progress,
        regime_edge_breakdown=regime_edge_breakdown,
    )
    operating_discipline = _operating_discipline(
        edge_proof_posture=edge_proof_posture,
        sample_progress=sample_progress,
        regime_edge_breakdown=regime_edge_breakdown,
    )
    experiment_sequence = _experiment_sequence(
        entry_timing=entry_timing,
        execution_style=execution_style,
        sample_progress=sample_progress,
    )
    return {
        "available": bool(source.get("available", False)),
        "advisory_only": bool(source.get("advisory_only", True)),
        "edge_state": str(source.get("edge_state") or "insufficient_edge_measurement"),
        "closed_trade_count": _int(true_edge.get("closed_trade_count", 0)),
        "true_edge_ratio": round(_float(true_edge.get("true_edge_ratio", 0.0)), 4),
        "recent_true_edge_ratio": round(_float(true_edge.get("recent_true_edge_ratio", 0.0)), 4),
        "prior_true_edge_ratio": round(_float(true_edge.get("prior_true_edge_ratio", 0.0)), 4),
        "edge_decay_rate": round(_float(true_edge.get("edge_decay_rate", 0.0)), 4),
        "edge_stability": round(_float(true_edge.get("edge_stability", 0.0)), 4),
        "closed_expected_r": round(_float(true_edge.get("closed_expected_r", 0.0)), 4),
        "post_cost_closed_realized_r": round(_float(true_edge.get("post_cost_closed_realized_r", 0.0)), 4),
        "entry_timing_available": bool(entry_timing.get("available", False)),
        "entry_timing_comparison_ready": bool(entry_timing.get("comparison_ready", False)),
        "entry_timing_preferred_variant": str(entry_timing.get("preferred_variant") or "none"),
        "entry_timing_recommendation_reason": str(entry_timing.get("recommendation_reason") or "not_available"),
        "execution_style_available": bool(execution_style.get("available", False)),
        "execution_style_comparison_ready": bool(execution_style.get("comparison_ready", False)),
        "execution_style_preferred_variant": str(execution_style.get("preferred_variant") or "none"),
        "execution_style_recommendation_reason": str(
            execution_style.get("recommendation_reason") or "not_available"
        ),
        "sample_maturity_state": str(sample_progress.get("sample_maturity_state") or "unknown"),
        "directional_ready": bool(sample_progress.get("directional_ready", False)),
        "decision_ready": bool(sample_progress.get("decision_ready", False)),
        "promotion_ready": bool(sample_progress.get("promotion_ready", False)),
        "operator_sample_floor_ready": bool(sample_progress.get("operator_sample_floor_ready", False)),
        "next_sample_target_closed_trades": _int(sample_progress.get("next_sample_target_closed_trades", 0)),
        "remaining_closed_trades_to_next_target": _int(
            sample_progress.get("remaining_closed_trades_to_next_target", 0)
        ),
        "edge_proof_goal_closed_trades": _int(sample_progress.get("edge_proof_goal_closed_trades", 0)),
        "edge_proof_goal_ready": bool(sample_progress.get("edge_proof_goal_ready", False)),
        "remaining_closed_trades_to_edge_proof_goal": _int(
            sample_progress.get("remaining_closed_trades_to_edge_proof_goal", 0)
        ),
        "regime_dependency_state": str(regime_edge_breakdown.get("dependency_state") or "not_available"),
        "regime_dependency_gap": round(_float(regime_edge_breakdown.get("dependency_gap", 0.0)), 4),
        "strongest_regime": str(strongest_regime.get("key") or "none"),
        "strongest_regime_true_edge_ratio": round(_float(strongest_regime.get("true_edge_ratio", 0.0)), 4),
        "weakest_regime": str(weakest_regime.get("key") or "none"),
        "weakest_regime_true_edge_ratio": round(_float(weakest_regime.get("true_edge_ratio", 0.0)), 4),
        "dominant_regime": str(dominant_regime.get("key") or "none"),
        "dominant_regime_closed_trade_count": _int(dominant_regime.get("closed", 0)),
        "edge_proof_posture": edge_proof_posture,
        "operating_discipline": operating_discipline,
        "experiment_sequence": experiment_sequence,
        "daily_edge_kpis": {
            "closed_trade_count": _int(true_edge.get("closed_trade_count", 0)),
            "sample_maturity_state": str(sample_progress.get("sample_maturity_state") or "unknown"),
            "true_edge_ratio": round(_float(true_edge.get("true_edge_ratio", 0.0)), 4),
            "true_edge_ratio_claim_threshold": 1.0,
            "edge_decay_rate": round(_float(true_edge.get("edge_decay_rate", 0.0)), 4),
            "edge_decay_watch_floor": -0.05,
            "regime_dependency_state": str(regime_edge_breakdown.get("dependency_state") or "not_available"),
        },
        "summary": str(source.get("summary") or ""),
        "reason_codes": list(source.get("reason_codes") or []),
        "source_summary": dict(source.get("source_summary") or {}),
        "true_edge": true_edge,
        "entry_timing_experiment": entry_timing,
        "execution_style_experiment": execution_style,
        "sample_progress": sample_progress,
        "regime_edge_breakdown": regime_edge_breakdown,
    }
