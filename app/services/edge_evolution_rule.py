from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


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


def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _confidence_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(str(value or "low"), 0)


def _raise_confidence(current: str, minimum: str) -> str:
    if _confidence_rank(current) >= _confidence_rank(minimum):
        return current
    return minimum


def _promotion_candidate(edge_summary: dict[str, Any]) -> dict[str, Any]:
    entry_preferred = str(edge_summary.get("entry_timing_preferred_variant") or "none")
    execution_preferred = str(edge_summary.get("execution_style_preferred_variant") or "none")
    entry_ready = bool(edge_summary.get("entry_timing_comparison_ready", False))
    execution_ready = bool(edge_summary.get("execution_style_comparison_ready", False))

    if entry_ready and entry_preferred not in {"", "none", "reaction_confirmed"}:
        return {
            "axis": "entry_timing",
            "preferred_variant": entry_preferred,
            "baseline_variant": "reaction_confirmed",
            "recommendation_reason": str(
                edge_summary.get("entry_timing_recommendation_reason") or "not_available"
            ),
            "comparison_ready": True,
        }
    if execution_ready and execution_preferred not in {"", "none", "market"}:
        return {
            "axis": "execution_style",
            "preferred_variant": execution_preferred,
            "baseline_variant": "market",
            "recommendation_reason": str(
                edge_summary.get("execution_style_recommendation_reason") or "not_available"
            ),
            "comparison_ready": True,
        }
    return {}


def _experiment_snapshot(edge_summary: dict[str, Any], *, axis: str) -> dict[str, Any]:
    source = _dict(edge_summary)
    if axis == "entry_timing":
        payload = _dict(source.get("entry_timing_experiment"))
        return payload or {
            "comparison_ready": bool(source.get("entry_timing_comparison_ready", False)),
            "preferred_variant": str(source.get("entry_timing_preferred_variant") or "none"),
            "recommendation_reason": str(source.get("entry_timing_recommendation_reason") or "not_available"),
        }
    if axis == "execution_style":
        payload = _dict(source.get("execution_style_experiment"))
        return payload or {
            "comparison_ready": bool(source.get("execution_style_comparison_ready", False)),
            "preferred_variant": str(source.get("execution_style_preferred_variant") or "none"),
            "recommendation_reason": str(source.get("execution_style_recommendation_reason") or "not_available"),
        }
    return {}


def _promotion_action(axis: str) -> str:
    if axis == "entry_timing":
        return "promote_entry_timing_branch_review"
    if axis == "execution_style":
        return "promote_execution_style_branch_review"
    return "promote_preferred_branch_review"


def _latest_review_packet(review_followup_ledger: dict[str, Any]) -> dict[str, Any]:
    ledger = _dict(review_followup_ledger)
    recent_packets = [
        _dict(item)
        for item in list(ledger.get("recent_packets") or [])
        if isinstance(item, dict)
    ]
    if recent_packets:
        return recent_packets[0]
    last_action = str(ledger.get("last_action") or "none")
    if last_action in {"", "none"}:
        return {}
    return {
        "action": last_action,
        "status": str(ledger.get("last_status") or "none"),
        "generated_at": str(ledger.get("last_generated_at") or ""),
        "recorded_at": str(ledger.get("last_recorded_at") or ""),
        "target_contract": _dict(ledger.get("last_target_contract")),
        "edge_experiment_review": {
            "closed_trade_count": _int(ledger.get("last_closed_trade_count", 0)),
            "true_edge_ratio": round(_float(ledger.get("last_true_edge_ratio")), 4),
            "recent_true_edge_ratio": round(_float(ledger.get("last_recent_true_edge_ratio")), 4),
            "prior_true_edge_ratio": round(_float(ledger.get("last_prior_true_edge_ratio")), 4),
            "edge_decay_rate": round(_float(ledger.get("last_edge_decay_rate")), 4),
            "entry_timing_preferred_variant": str(ledger.get("last_entry_timing_preferred_variant") or "none"),
            "execution_style_preferred_variant": str(
                ledger.get("last_execution_style_preferred_variant") or "none"
            ),
        },
        "edge_evolution_rule": {
            "evolution_state": str(ledger.get("last_evolution_state") or "insufficient_sample"),
            "recommended_action": str(ledger.get("last_recommended_action") or "keep_current_baseline"),
            "allocation_bias": str(ledger.get("last_allocation_bias") or "hold_current_baseline"),
            "confidence": str(ledger.get("last_confidence") or "low"),
            "recommendation_strength": str(ledger.get("last_recommendation_strength") or "baseline"),
            "promotion_candidate_axis": str(ledger.get("last_promotion_candidate_axis") or "none"),
            "promotion_candidate_variant": str(ledger.get("last_promotion_candidate_variant") or "none"),
        },
    }


def _review_axis(*, action: str, target_contract: dict[str, Any], promotion_candidate: dict[str, Any]) -> str:
    if action in {"run_entry_timing_split_review", "promote_entry_timing_branch_review"}:
        return "entry_timing"
    if action in {"run_execution_style_split_review", "promote_execution_style_branch_review"}:
        return "execution_style"
    target_axis = str(target_contract.get("axis") or "")
    if target_axis in {"entry_timing", "execution_style"}:
        return target_axis
    candidate_axis = str(promotion_candidate.get("axis") or "")
    if candidate_axis in {"entry_timing", "execution_style"}:
        return candidate_axis
    return "branch"


def _closed_loop_feedback(
    *,
    edge_summary: dict[str, Any],
    review_followup_ledger: dict[str, Any] | None,
    promotion_candidate: dict[str, Any],
) -> dict[str, Any]:
    ledger = _dict(review_followup_ledger)
    packet = _latest_review_packet(ledger)
    if not packet:
        return {
            "available": False,
            "confirmation_state": "not_available",
            "recommendation_strength": "baseline",
            "reason": "review_followup_ledger_unavailable",
        }

    action = str(packet.get("action") or "none")
    status = str(packet.get("status") or "UNKNOWN")
    target_contract = _dict(packet.get("target_contract"))
    prior_edge = _dict(packet.get("edge_experiment_review"))
    current_closed_trade_count = _int(edge_summary.get("closed_trade_count", 0))
    prior_closed_trade_count = _int(
        prior_edge.get("closed_trade_count", ledger.get("last_closed_trade_count", 0))
    )
    new_closed_trade_count = max(current_closed_trade_count - prior_closed_trade_count, 0)
    current_true_edge_ratio = round(_float(edge_summary.get("true_edge_ratio", 0.0)), 4)
    prior_true_edge_ratio = round(
        _float(prior_edge.get("true_edge_ratio", ledger.get("last_true_edge_ratio", 0.0))),
        4,
    )
    current_recent_true_edge_ratio = round(_float(edge_summary.get("recent_true_edge_ratio", 0.0)), 4)
    prior_recent_true_edge_ratio = round(
        _float(prior_edge.get("recent_true_edge_ratio", ledger.get("last_recent_true_edge_ratio", 0.0))),
        4,
    )
    edge_decay_rate = round(_float(edge_summary.get("edge_decay_rate", 0.0)), 4)
    edge_state = str(edge_summary.get("edge_state") or "insufficient_edge_measurement")
    comparison_axis = _review_axis(
        action=action,
        target_contract=target_contract,
        promotion_candidate=promotion_candidate,
    )
    experiment_snapshot = _experiment_snapshot(edge_summary, axis=comparison_axis)
    preferred_variant = str(experiment_snapshot.get("preferred_variant") or "none")
    prior_preferred_variant = str(target_contract.get("preferred_variant") or "none")
    if prior_preferred_variant in {"", "none"} and comparison_axis == "entry_timing":
        prior_preferred_variant = str(
            prior_edge.get("entry_timing_preferred_variant") or ledger.get("last_entry_timing_preferred_variant") or "none"
        )
    elif prior_preferred_variant in {"", "none"} and comparison_axis == "execution_style":
        prior_preferred_variant = str(
            prior_edge.get("execution_style_preferred_variant")
            or ledger.get("last_execution_style_preferred_variant")
            or "none"
        )
    preferred_variant_persisted = prior_preferred_variant in {"", "none"} or preferred_variant == prior_preferred_variant
    true_edge_gap = abs(_float(experiment_snapshot.get("true_edge_ratio_gap", 0.0)))
    capture_gap = abs(_float(experiment_snapshot.get("capture_ratio_gap", 0.0)))
    branch_gap = round(max(true_edge_gap, capture_gap), 4)

    feedback = {
        "available": True,
        "prior_action": action,
        "prior_status": status,
        "prior_generated_at": str(packet.get("generated_at") or ""),
        "prior_recorded_at": str(packet.get("recorded_at") or ""),
        "prior_closed_trade_count": prior_closed_trade_count,
        "current_closed_trade_count": current_closed_trade_count,
        "new_closed_trade_count": new_closed_trade_count,
        "prior_true_edge_ratio": prior_true_edge_ratio,
        "current_true_edge_ratio": current_true_edge_ratio,
        "current_recent_true_edge_ratio": current_recent_true_edge_ratio,
        "prior_recent_true_edge_ratio": prior_recent_true_edge_ratio,
        "comparison_axis": comparison_axis,
        "preferred_variant": preferred_variant,
        "prior_preferred_variant": prior_preferred_variant,
        "preferred_variant_persisted": preferred_variant_persisted,
        "branch_gap": branch_gap,
        "confirmation_state": "below_confirmation_threshold",
        "recommendation_strength": "baseline",
        "reason": "closed_loop_threshold_not_met",
    }

    if status != "READY":
        feedback["confirmation_state"] = "waiting_for_ready_packet"
        feedback["reason"] = "latest_review_packet_is_not_ready"
        return feedback

    if new_closed_trade_count <= 0:
        feedback["confirmation_state"] = "waiting_for_new_closes"
        feedback["reason"] = "no_new_closed_trades_since_last_review_packet"
        return feedback

    if action == "review_edge_kill_condition":
        if current_true_edge_ratio <= 0.68 or edge_decay_rate <= -0.20:
            feedback["confirmation_state"] = "kill_confirmed"
            feedback["recommendation_strength"] = "escalated"
            feedback["reason"] = "kill_review_remains_breached_after_new_closes"
        elif current_true_edge_ratio >= 0.90 and edge_state in {"watch_edge", "healthy_edge"}:
            feedback["confirmation_state"] = "direction_reversed"
            feedback["reason"] = "edge_recovered_after_kill_review_packet"
        return feedback

    if action == "reduce_baseline_allocation_review":
        if current_true_edge_ratio <= 0.68 or edge_decay_rate <= -0.20:
            feedback["confirmation_state"] = "kill_confirmed"
            feedback["recommendation_strength"] = "escalated"
            feedback["reason"] = "reduce_review_worsened_into_kill_threshold"
        elif (
            edge_state == "fragile_edge"
            or current_true_edge_ratio <= 0.80
            or edge_decay_rate <= -0.15
            or current_recent_true_edge_ratio <= min(prior_recent_true_edge_ratio, 0.80)
        ):
            feedback["confirmation_state"] = "reduce_confirmed"
            feedback["recommendation_strength"] = "confirmed"
            feedback["reason"] = "reduce_review_remains_confirmed_after_new_closes"
        elif current_true_edge_ratio >= 0.95 and edge_state == "healthy_edge":
            feedback["confirmation_state"] = "direction_reversed"
            feedback["reason"] = "edge_recovered_after_reduce_review_packet"
        return feedback

    if action in {
        "run_entry_timing_split_review",
        "run_execution_style_split_review",
        "promote_entry_timing_branch_review",
        "promote_execution_style_branch_review",
        "promote_preferred_branch_review",
    }:
        if not preferred_variant_persisted:
            feedback["confirmation_state"] = "direction_reversed"
            feedback["reason"] = "preferred_variant_changed_after_review_packet"
            return feedback
        if (
            bool(experiment_snapshot.get("comparison_ready", False))
            and current_closed_trade_count >= 6
            and current_true_edge_ratio >= 1.0
            and edge_decay_rate > -0.05
            and (
                branch_gap >= 0.10
                or current_true_edge_ratio >= prior_true_edge_ratio + 0.05
                or current_recent_true_edge_ratio >= prior_recent_true_edge_ratio + 0.05
            )
        ):
            feedback["confirmation_state"] = "promote_confirmed"
            feedback["recommendation_strength"] = "confirmed"
            feedback["reason"] = "preferred_branch_outperformance_persisted_after_new_closes"
        elif current_true_edge_ratio < 0.95 or edge_state == "fragile_edge":
            feedback["confirmation_state"] = "direction_reversed"
            feedback["reason"] = "promotion_direction_lost_after_review_packet"
        return feedback

    return feedback


def build_edge_evolution_rule(
    *,
    edge_experiment_review: dict[str, Any] | None,
    rollout_recommendation: dict[str, Any] | None = None,
    strategy_lifecycle: dict[str, Any] | None = None,
    kill_condition_automation: dict[str, Any] | None = None,
    review_followup_ledger: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    edge_summary = _dict(edge_experiment_review)
    if not edge_summary or not bool(edge_summary.get("available", False)):
        return None

    rollout_summary = _dict(rollout_recommendation)
    lifecycle_summary = _dict(strategy_lifecycle)
    kill_summary = _dict(kill_condition_automation)

    true_edge_ratio = round(_float(edge_summary.get("true_edge_ratio", 0.0)), 4)
    edge_decay_rate = round(_float(edge_summary.get("edge_decay_rate", 0.0)), 4)
    closed_trade_count = _int(edge_summary.get("closed_trade_count", 0))
    edge_state = str(edge_summary.get("edge_state") or "insufficient_edge_measurement")
    rollout_state = str(rollout_summary.get("recommendation") or "hold").lower()
    lifecycle_state = str(lifecycle_summary.get("state") or "unknown").lower()
    kill_condition_state = str(kill_summary.get("kill_condition_state") or "observe_only").lower()
    promotion_candidate = _promotion_candidate(edge_summary)
    closed_loop_feedback = _closed_loop_feedback(
        edge_summary=edge_summary,
        review_followup_ledger=review_followup_ledger,
        promotion_candidate=promotion_candidate,
    )
    closed_loop_confirmation_state = str(closed_loop_feedback.get("confirmation_state") or "not_available")
    regime_dependency_state = str(edge_summary.get("regime_dependency_state") or "not_available")
    strongest_regime = str(edge_summary.get("strongest_regime") or "none")
    weakest_regime = str(edge_summary.get("weakest_regime") or "none")
    weakest_regime_true_edge_ratio = round(_float(edge_summary.get("weakest_regime_true_edge_ratio", 0.0)), 4)
    regime_guard_state = "not_applicable"

    if closed_trade_count >= 8 and edge_state == "healthy_edge":
        confidence = "high"
    elif closed_trade_count >= 6:
        confidence = "medium"
    else:
        confidence = "low"

    if closed_trade_count < 4:
        evolution_state = "insufficient_sample"
        recommended_action = "keep_research_only_until_sample_matures"
        allocation_bias = "keep_research_only"
        summary = (
            "Closed-trade edge evidence is still too thin to change allocation; keep research-only posture until more "
            "post-cost outcomes accumulate."
        )
    elif kill_condition_state in {"close_only_review", "kill_switch_review"} and (
        true_edge_ratio < 0.7 or edge_decay_rate <= -0.2
    ):
        evolution_state = "edge_kill_review"
        recommended_action = "review_edge_kill_condition"
        allocation_bias = "reduce_or_stop"
        summary = (
            "Edge has deteriorated enough that edge-based kill review should happen before trusting further live "
            "allocation."
        )
    elif edge_state == "fragile_edge" or true_edge_ratio < 0.8 or edge_decay_rate <= -0.15:
        evolution_state = "reduce_candidate"
        recommended_action = "reduce_baseline_allocation_review"
        allocation_bias = "reduce_baseline"
        summary = (
            "Baseline edge is weak enough that allocation should be reduced until the preferred branch proves "
            "durable post-cost."
        )
    elif (
        promotion_candidate
        and closed_trade_count >= 6
        and true_edge_ratio >= 1.0
        and edge_decay_rate > -0.05
        and edge_state in {"healthy_edge", "watch_edge"}
    ):
        axis = str(promotion_candidate.get("axis") or "branch")
        preferred_variant = str(promotion_candidate.get("preferred_variant") or "none")
        evolution_state = "promote_candidate"
        recommended_action = f"promote_{axis}_branch_review"
        allocation_bias = "promote_preferred_branch"
        summary = (
            f"Preferred {axis} branch ({preferred_variant}) is outperforming the baseline strongly enough to justify "
            "promotion review before broader rollout changes."
        )
    elif rollout_state == "research_only" or lifecycle_state in {"research", "probation"}:
        evolution_state = "research_only"
        recommended_action = "keep_research_only_until_sample_matures"
        allocation_bias = "keep_research_only"
        summary = (
            "Current edge evidence is directional but not mature enough for strategy mutation; keep research-only "
            "posture while experiments continue."
        )
    else:
        evolution_state = "hold_baseline"
        recommended_action = "keep_current_baseline"
        allocation_bias = "hold_current_baseline"
        summary = (
            "Current edge evidence is stable enough to hold the baseline while controlled branch experiments continue."
        )
    recommendation_strength = "baseline"

    if regime_dependency_state == "regime_dependent" and weakest_regime_true_edge_ratio > 0.0:
        if confidence == "high":
            confidence = "medium"
        elif confidence == "medium":
            confidence = "low"
        regime_guard_state = "watch_regime_dependency"
        if (
            evolution_state == "promote_candidate"
            and (closed_trade_count < 20 or weakest_regime_true_edge_ratio < 0.90)
        ):
            evolution_state = "research_only"
            recommended_action = "keep_research_only_until_sample_matures"
            allocation_bias = "keep_research_only"
            summary = (
                "Preferred branch is improving, but the edge is still regime-dependent and the weakest regime has not "
                "cleared a durable threshold; keep the branch in experiment mode until more closes accumulate."
            )
            regime_guard_state = "promotion_blocked_by_regime_dependency"

    if closed_loop_confirmation_state == "kill_confirmed":
        evolution_state = "edge_kill_review"
        recommended_action = "review_edge_kill_condition"
        allocation_bias = "reduce_or_stop"
        confidence = "high"
        recommendation_strength = "escalated"
        summary = (
            "Recent closed-trade outcomes confirmed the prior reduction/kill review direction; escalate kill review "
            "before trusting further live allocation."
        )
    elif closed_loop_confirmation_state == "reduce_confirmed":
        evolution_state = "reduce_candidate"
        recommended_action = "reduce_baseline_allocation_review"
        allocation_bias = "reduce_baseline"
        confidence = _raise_confidence(confidence, "high" if closed_trade_count >= 8 else "medium")
        recommendation_strength = "confirmed"
        summary = (
            "Recent closed-trade outcomes confirmed the prior reduction review; keep baseline allocation reduced "
            "until post-cost edge recovers."
        )
    elif closed_loop_confirmation_state == "promote_confirmed" and promotion_candidate:
        axis = str(closed_loop_feedback.get("comparison_axis") or promotion_candidate.get("axis") or "branch")
        preferred_variant = str(
            closed_loop_feedback.get("preferred_variant") or promotion_candidate.get("preferred_variant") or "none"
        )
        evolution_state = "promote_candidate"
        recommended_action = _promotion_action(axis)
        allocation_bias = "promote_preferred_branch"
        confidence = _raise_confidence(confidence, "high")
        recommendation_strength = "confirmed"
        summary = (
            f"Recent closed-trade outcomes confirmed the preferred {axis} branch ({preferred_variant}); "
            "promotion review is now better supported than a fresh exploratory split."
        )

    reason_codes = _dedupe(
        [
            f"evolution_state:{evolution_state}",
            f"recommended_action:{recommended_action}",
            f"recommendation_strength:{recommendation_strength}",
            f"edge_state:{edge_state}",
            f"true_edge_ratio:{true_edge_ratio:.4f}",
            f"edge_decay_rate:{edge_decay_rate:+.4f}",
            f"rollout_recommendation:{rollout_state}" if rollout_state else "",
            f"strategy_lifecycle:{lifecycle_state}" if lifecycle_state else "",
            f"kill_condition:{kill_condition_state}" if kill_condition_state else "",
            f"closed_loop:{closed_loop_confirmation_state}",
            (
                f"closed_loop_prior_action:{closed_loop_feedback.get('prior_action')}"
                if closed_loop_feedback.get("available")
                else ""
            ),
            f"regime_dependency:{regime_dependency_state}",
            (
                f"weakest_regime:{weakest_regime}:{weakest_regime_true_edge_ratio:.4f}"
                if weakest_regime not in {"", "none"}
                else ""
            ),
            f"regime_guard:{regime_guard_state}",
            (
                f"promotion_candidate:{promotion_candidate.get('axis')}:{promotion_candidate.get('preferred_variant')}"
                if promotion_candidate
                else ""
            ),
        ]
    )

    return {
        "available": True,
        "advisory_only": True,
        "evolution_state": evolution_state,
        "recommended_action": recommended_action,
        "allocation_bias": allocation_bias,
        "confidence": confidence,
        "recommendation_strength": recommendation_strength,
        "closed_loop_confirmation_state": closed_loop_confirmation_state,
        "kill_review_triggered": bool(evolution_state == "edge_kill_review"),
        "summary": summary,
        "reason_codes": reason_codes,
        "source_summary": {
            "edge_state": edge_state,
            "rollout_recommendation": rollout_state or "hold",
            "strategy_lifecycle_state": lifecycle_state or "unknown",
            "kill_condition_state": kill_condition_state or "observe_only",
            "entry_timing_preferred_variant": str(edge_summary.get("entry_timing_preferred_variant") or "none"),
            "execution_style_preferred_variant": str(edge_summary.get("execution_style_preferred_variant") or "none"),
            "review_followup_last_action": str(_dict(review_followup_ledger).get("last_action") or "none"),
            "review_followup_last_status": str(_dict(review_followup_ledger).get("last_status") or "none"),
            "regime_dependency_state": regime_dependency_state,
            "strongest_regime": strongest_regime,
            "weakest_regime": weakest_regime,
            "regime_guard_state": regime_guard_state,
        },
        "true_edge_ratio": true_edge_ratio,
        "edge_decay_rate": edge_decay_rate,
        "closed_trade_count": closed_trade_count,
        "regime_guard_state": regime_guard_state,
        "strongest_regime": strongest_regime,
        "weakest_regime": weakest_regime,
        "weakest_regime_true_edge_ratio": weakest_regime_true_edge_ratio,
        "promotion_candidate": promotion_candidate or None,
        "closed_loop_feedback": closed_loop_feedback,
    }


def summarize_edge_evolution_rule(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    source = _dict(payload)
    if not source:
        return None
    promotion_candidate = _dict(source.get("promotion_candidate"))
    source_summary = _dict(source.get("source_summary"))
    closed_loop_feedback = _dict(source.get("closed_loop_feedback"))
    return {
        "available": bool(source.get("available", False)),
        "advisory_only": bool(source.get("advisory_only", True)),
        "evolution_state": str(source.get("evolution_state") or "insufficient_sample"),
        "recommended_action": str(source.get("recommended_action") or "keep_current_baseline"),
        "allocation_bias": str(source.get("allocation_bias") or "hold_current_baseline"),
        "confidence": str(source.get("confidence") or "low"),
        "recommendation_strength": str(source.get("recommendation_strength") or "baseline"),
        "closed_loop_confirmation_state": str(
            source.get("closed_loop_confirmation_state")
            or closed_loop_feedback.get("confirmation_state")
            or "not_available"
        ),
        "kill_review_triggered": bool(source.get("kill_review_triggered", False)),
        "true_edge_ratio": round(_float(source.get("true_edge_ratio", 0.0)), 4),
        "edge_decay_rate": round(_float(source.get("edge_decay_rate", 0.0)), 4),
        "closed_trade_count": _int(source.get("closed_trade_count", 0)),
        "regime_guard_state": str(source.get("regime_guard_state") or "not_applicable"),
        "strongest_regime": str(source.get("strongest_regime") or "none"),
        "weakest_regime": str(source.get("weakest_regime") or "none"),
        "weakest_regime_true_edge_ratio": round(_float(source.get("weakest_regime_true_edge_ratio", 0.0)), 4),
        "promotion_candidate_axis": str(promotion_candidate.get("axis") or "none"),
        "promotion_candidate_variant": str(promotion_candidate.get("preferred_variant") or "none"),
        "promotion_candidate_reason": str(promotion_candidate.get("recommendation_reason") or "not_available"),
        "summary": str(source.get("summary") or ""),
        "reason_codes": list(source.get("reason_codes") or []),
        "source_summary": source_summary,
        "promotion_candidate": promotion_candidate or None,
        "closed_loop_feedback": closed_loop_feedback or None,
    }
