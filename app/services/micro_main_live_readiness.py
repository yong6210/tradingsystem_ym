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
class MicroMainLiveReadiness:
    symbol: str
    enabled: bool
    shadow_only: bool
    tier: str
    rollout_priority: int
    risk_multiplier: float
    status: str
    ready_for_partial: bool
    blockers: tuple[str, ...]
    shadow_metrics: dict[str, Any]


def evaluate_micro_main_live_readiness(
    *,
    symbol: str,
    shadow_summary: dict[str, Any] | None,
    universe_policy: dict[str, Any] | None,
    enabled: bool,
    shadow_only: bool,
    partial_ratio: float,
    core_live_slots: int,
    secondary_live_enabled: bool,
) -> MicroMainLiveReadiness:
    normalized_symbol = str(symbol or "").upper()
    shadow = dict(shadow_summary or {})
    policy = dict(universe_policy or {})
    entries = list(policy.get("entries") or [])
    entry = next((item for item in entries if str(item.get("symbol") or "").upper() == normalized_symbol), None)

    tier = str((entry or {}).get("tier") or "unassigned")
    rollout_priority = int((entry or {}).get("rollout_priority", 0) or 0)
    risk_multiplier = float((entry or {}).get("risk_multiplier", 0.0) or 0.0)

    enabled = _safe_bool(enabled)
    shadow_only = _safe_bool(shadow_only)
    secondary_live_enabled = _safe_bool(secondary_live_enabled)
    available = _safe_bool(shadow.get("available", False))
    decision = str(shadow.get("decision") or "REJECT").upper()
    recent_closed = int(shadow.get("recent_closed", 0) or 0)
    ev_r = float(shadow.get("ev_r", 0.0) or 0.0)
    total_r = float(shadow.get("total_r", 0.0) or 0.0)
    win_rate = float(shadow.get("win_rate", 0.0) or 0.0)

    blockers: list[str] = []
    if not enabled:
        blockers.append("family_disabled")
    if entry is None:
        blockers.append("symbol_not_in_universe")
    if not available:
        blockers.append("shadow_not_available")
    if recent_closed <= 0:
        blockers.append("no_recent_closed_sample")
    if decision != "PASS":
        blockers.append("shadow_decision_not_pass")
    if ev_r < 0.20:
        blockers.append("recent_shadow_ev_below_floor")
    if total_r <= 0.0:
        blockers.append("recent_shadow_total_not_positive")
    if tier == "secondary" and not secondary_live_enabled:
        blockers.append("secondary_rollout_disabled")
    if tier == "core" and core_live_slots > 0 and rollout_priority > core_live_slots:
        blockers.append("outside_current_core_live_window")

    ready_for_partial = not blockers and shadow_only

    if not enabled:
        status = "disabled"
    elif entry is None:
        status = "not_in_universe"
    elif not available:
        status = "shadow_unavailable"
    elif tier == "secondary" and not secondary_live_enabled:
        status = "secondary_shadow_only"
    elif recent_closed <= 0:
        status = "waiting_fresh_setup"
    elif ready_for_partial:
        status = "shadow_ready_for_partial"
    elif blockers:
        status = "shadow_collecting"
    elif shadow_only:
        status = "shadow_collecting"
    else:
        status = "partial_or_live_running"

    return MicroMainLiveReadiness(
        symbol=normalized_symbol,
        enabled=enabled,
        shadow_only=shadow_only,
        tier=tier,
        rollout_priority=rollout_priority,
        risk_multiplier=risk_multiplier,
        status=status,
        ready_for_partial=ready_for_partial,
        blockers=tuple(blockers),
        shadow_metrics={
            "decision": decision,
            "recent_closed": recent_closed,
            "ev_r": ev_r,
            "total_r": total_r,
            "win_rate": win_rate,
            "recent_window_hours": float(shadow.get("recent_window_hours", 0.0) or 0.0),
            "latest_trade": dict(shadow.get("latest_trade") or {}) or None,
            "partial_activation_ratio": round(float(partial_ratio), 4),
            "core_live_slots": int(core_live_slots),
            "secondary_live_enabled": secondary_live_enabled,
        },
    )


def micro_main_live_readiness_to_dict(payload: MicroMainLiveReadiness) -> dict[str, Any]:
    return {
        "symbol": payload.symbol,
        "enabled": payload.enabled,
        "shadow_only": payload.shadow_only,
        "tier": payload.tier,
        "rollout_priority": payload.rollout_priority,
        "risk_multiplier": round(float(payload.risk_multiplier), 4),
        "status": payload.status,
        "ready_for_partial": payload.ready_for_partial,
        "blockers": list(payload.blockers),
        "shadow_metrics": dict(payload.shadow_metrics),
    }
