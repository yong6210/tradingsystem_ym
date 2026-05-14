from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(default)


@dataclass(frozen=True, slots=True)
class TransitionVariantReadiness:
    symbol: str
    enabled: bool
    shadow_only: bool
    killed: bool
    status: str
    ready_for_partial: bool
    blockers: tuple[str, ...]
    advisory_blockers: tuple[str, ...]
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

    enabled = _safe_bool(variant.get("enabled", False))
    shadow_only = _safe_bool(variant.get("shadow_only", True), default=True)
    killed = _safe_bool(variant.get("killed", False))
    shadow_pass_count = int(shadow.get("shadow_pass_count", 0) or 0)
    shadow_evaluated_count = int(shadow.get("shadow_evaluated_count", 0) or 0)
    low_conf_delta = int(shadow.get("low_confluence_block_delta", 0) or 0)
    candidate_delta = int(shadow.get("shadow_candidate_delta", 0) or 0)
    expected_ev_proxy = float(shadow.get("expected_ev_r_proxy", 0.0) or 0.0)

    blockers: list[str] = []
    shadow_evidence_blockers: list[str] = []
    if not enabled:
        blockers.append("variant_disabled")
    if killed:
        blockers.append("variant_killed")
    if shadow_evaluated_count <= 0:
        shadow_evidence_blockers.append("no_shadow_evaluations")
    if shadow_pass_count < 2:
        shadow_evidence_blockers.append("shadow_pass_count_below_minimum")
    if low_conf_delta >= 0:
        shadow_evidence_blockers.append("low_confluence_not_reduced")
    if candidate_delta <= 0:
        shadow_evidence_blockers.append("candidate_delta_not_positive")
    if expected_ev_proxy <= 0.0:
        shadow_evidence_blockers.append("expected_ev_proxy_not_positive")

    advisory_blockers: list[str] = []
    if shadow_only:
        blockers.extend(shadow_evidence_blockers)
    else:
        advisory_blockers.extend(shadow_evidence_blockers)

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
    elif advisory_blockers:
        status = "live_observing_shadow_evidence"
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
        advisory_blockers=tuple(advisory_blockers),
        shadow_metrics={
            "shadow_evaluated_count": shadow_evaluated_count,
            "shadow_pass_count": shadow_pass_count,
            "shadow_pass_rate": float(shadow.get("shadow_pass_rate", 0.0) or 0.0),
            "shadow_candidate_delta": candidate_delta,
            "low_confluence_block_delta": low_conf_delta,
            "expected_ev_r_proxy": expected_ev_proxy,
            "reason_mix": dict(shadow.get("shadow_rescue_reason_mix") or {}),
            "shadow_evidence_policy": "hard_gate_in_shadow_only_advisory_in_live_enabled",
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
        "advisory_blockers": list(payload.advisory_blockers),
        "shadow_metrics": dict(payload.shadow_metrics),
        "live_lane": dict(payload.live_lane),
    }
