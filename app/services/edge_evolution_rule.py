from __future__ import annotations

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


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


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


def build_edge_evolution_rule(
    *,
    edge_experiment_review: dict[str, Any] | None,
    rollout_recommendation: dict[str, Any] | None = None,
    strategy_lifecycle: dict[str, Any] | None = None,
    kill_condition_automation: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    edge_summary = dict(edge_experiment_review or {})
    if not edge_summary or not bool(edge_summary.get("available", False)):
        return None

    rollout_summary = dict(rollout_recommendation or {})
    lifecycle_summary = dict(strategy_lifecycle or {})
    kill_summary = dict(kill_condition_automation or {})

    true_edge_ratio = round(_float(edge_summary.get("true_edge_ratio", 0.0)), 4)
    edge_decay_rate = round(_float(edge_summary.get("edge_decay_rate", 0.0)), 4)
    closed_trade_count = _int(edge_summary.get("closed_trade_count", 0))
    edge_state = str(edge_summary.get("edge_state") or "insufficient_edge_measurement")
    rollout_state = str(rollout_summary.get("recommendation") or "hold").lower()
    lifecycle_state = str(lifecycle_summary.get("state") or "unknown").lower()
    kill_condition_state = str(kill_summary.get("kill_condition_state") or "observe_only").lower()
    promotion_candidate = _promotion_candidate(edge_summary)

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

    reason_codes = _dedupe(
        [
            f"evolution_state:{evolution_state}",
            f"recommended_action:{recommended_action}",
            f"edge_state:{edge_state}",
            f"true_edge_ratio:{true_edge_ratio:.4f}",
            f"edge_decay_rate:{edge_decay_rate:+.4f}",
            f"rollout_recommendation:{rollout_state}" if rollout_state else "",
            f"strategy_lifecycle:{lifecycle_state}" if lifecycle_state else "",
            f"kill_condition:{kill_condition_state}" if kill_condition_state else "",
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
        },
        "true_edge_ratio": true_edge_ratio,
        "edge_decay_rate": edge_decay_rate,
        "closed_trade_count": closed_trade_count,
        "promotion_candidate": promotion_candidate or None,
    }


def summarize_edge_evolution_rule(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    source = dict(payload or {})
    if not source:
        return None
    promotion_candidate = dict(source.get("promotion_candidate") or {})
    source_summary = dict(source.get("source_summary") or {})
    return {
        "available": bool(source.get("available", False)),
        "advisory_only": bool(source.get("advisory_only", True)),
        "evolution_state": str(source.get("evolution_state") or "insufficient_sample"),
        "recommended_action": str(source.get("recommended_action") or "keep_current_baseline"),
        "allocation_bias": str(source.get("allocation_bias") or "hold_current_baseline"),
        "confidence": str(source.get("confidence") or "low"),
        "kill_review_triggered": bool(source.get("kill_review_triggered", False)),
        "true_edge_ratio": round(_float(source.get("true_edge_ratio", 0.0)), 4),
        "edge_decay_rate": round(_float(source.get("edge_decay_rate", 0.0)), 4),
        "closed_trade_count": _int(source.get("closed_trade_count", 0)),
        "promotion_candidate_axis": str(promotion_candidate.get("axis") or "none"),
        "promotion_candidate_variant": str(promotion_candidate.get("preferred_variant") or "none"),
        "promotion_candidate_reason": str(promotion_candidate.get("recommendation_reason") or "not_available"),
        "summary": str(source.get("summary") or ""),
        "reason_codes": list(source.get("reason_codes") or []),
        "source_summary": source_summary,
        "promotion_candidate": promotion_candidate or None,
    }
