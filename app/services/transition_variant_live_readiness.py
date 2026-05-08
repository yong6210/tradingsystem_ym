from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TransitionVariantReadiness:
    symbol: str
    enabled: bool
    shadow_only: bool
    killed: bool
    status: str
    ready_for_partial: bool
    blockers: tuple[str, ...]
    shadow_metrics: dict[str, Any]
    live_lane: dict[str, Any]


def evaluate_transition_variant_live_readiness(
    *,
    symbol: str,
    dashboard_payload: dict[str, Any] | None,
    safety_payload: dict[str, Any] | None,
) -> TransitionVariantReadiness:
    dashboard = dict(dashboard_payload or {})
    safety = dict(safety_payload or {})
    variant = dict(safety.get("transition_edge_variant") or {})
    shadow = dict((dashboard.get("active_contract") or {}).get("transition_edge_variant_shadow") or {})
    live_lane = dict(variant.get("live_lane") or {})

    enabled = bool(variant.get("enabled", False))
    shadow_only = bool(variant.get("shadow_only", True))
    killed = bool(variant.get("killed", False))
    shadow_pass_count = int(shadow.get("shadow_pass_count", 0) or 0)
    shadow_evaluated_count = int(shadow.get("shadow_evaluated_count", 0) or 0)
    low_conf_delta = int(shadow.get("low_confluence_block_delta", 0) or 0)
    candidate_delta = int(shadow.get("shadow_candidate_delta", 0) or 0)
    expected_ev_proxy = float(shadow.get("expected_ev_r_proxy", 0.0) or 0.0)

    blockers: list[str] = []
    if not enabled:
        blockers.append("variant_disabled")
    if killed:
        blockers.append("variant_killed")
    if shadow_evaluated_count <= 0:
        blockers.append("no_shadow_evaluations")
    if shadow_pass_count < 2:
        blockers.append("shadow_pass_count_below_minimum")
    if low_conf_delta >= 0:
        blockers.append("low_confluence_not_reduced")
    if candidate_delta <= 0:
        blockers.append("candidate_delta_not_positive")
    if expected_ev_proxy <= 0.0:
        blockers.append("expected_ev_proxy_not_positive")

    ready_for_partial = not blockers and shadow_only

    if killed:
        status = "killed"
    elif not enabled:
        status = "disabled"
    elif shadow_only and ready_for_partial:
        status = "shadow_ready_for_partial"
    elif shadow_only and shadow_pass_count <= 0:
        status = "waiting_shadow_signal"
    elif shadow_only:
        status = "shadow_collecting"
    else:
        status = "partial_or_live_running"

    return TransitionVariantReadiness(
        symbol=str(symbol).upper(),
        enabled=enabled,
        shadow_only=shadow_only,
        killed=killed,
        status=status,
        ready_for_partial=ready_for_partial,
        blockers=tuple(blockers),
        shadow_metrics={
            "shadow_evaluated_count": shadow_evaluated_count,
            "shadow_pass_count": shadow_pass_count,
            "shadow_pass_rate": float(shadow.get("shadow_pass_rate", 0.0) or 0.0),
            "shadow_candidate_delta": candidate_delta,
            "low_confluence_block_delta": low_conf_delta,
            "expected_ev_r_proxy": expected_ev_proxy,
            "reason_mix": dict(shadow.get("shadow_rescue_reason_mix") or {}),
        },
        live_lane=live_lane,
    )


def readiness_to_dict(payload: TransitionVariantReadiness) -> dict[str, Any]:
    return {
        "symbol": payload.symbol,
        "enabled": payload.enabled,
        "shadow_only": payload.shadow_only,
        "killed": payload.killed,
        "status": payload.status,
        "ready_for_partial": payload.ready_for_partial,
        "blockers": list(payload.blockers),
        "shadow_metrics": dict(payload.shadow_metrics),
        "live_lane": dict(payload.live_lane),
    }
