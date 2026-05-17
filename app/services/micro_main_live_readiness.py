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


def _quote_suffix(symbol: str) -> str:
    normalized = str(symbol or "").upper().strip()
    for quote in ("USDT", "USDC"):
        if normalized.endswith(quote):
            return quote
    return ""


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
    advisory_blockers: tuple[str, ...]
    shadow_metrics: dict[str, Any]


def _core_live_rank(*, entries: list[Any], symbol: str) -> int:
    quote = _quote_suffix(symbol)
    core_entries = [
        item
        for item in entries
        if str(dict(item).get("tier") or "").strip().lower() == "core"
        and (not quote or _quote_suffix(str(dict(item).get("symbol") or "")) == quote)
    ]
    ordered_core_symbols = [
        str(dict(item).get("symbol") or "").upper()
        for item in sorted(core_entries, key=lambda row: int(dict(row).get("rollout_priority", 0) or 0))
    ]
    try:
        return ordered_core_symbols.index(str(symbol or "").upper()) + 1
    except ValueError:
        return 0


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
    core_live_rank = _core_live_rank(entries=entries, symbol=normalized_symbol) if tier == "core" else 0
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
    shadow_evidence_blockers: list[str] = []
    if not enabled:
        blockers.append("family_disabled")
    if entry is None:
        blockers.append("symbol_not_in_universe")
    if not available:
        shadow_evidence_blockers.append("shadow_not_available")
    if recent_closed <= 0:
        shadow_evidence_blockers.append("no_recent_closed_sample")
    else:
        if decision != "PASS":
            shadow_evidence_blockers.append("shadow_decision_not_pass")
        if ev_r < 0.20:
            shadow_evidence_blockers.append("recent_shadow_ev_below_floor")
        if total_r <= 0.0:
            shadow_evidence_blockers.append("recent_shadow_total_not_positive")
    if tier == "secondary" and not secondary_live_enabled:
        blockers.append("secondary_rollout_disabled")
    if tier == "core" and core_live_slots > 0 and core_live_rank > core_live_slots:
        blockers.append("outside_current_core_live_window")

    advisory_blockers: list[str] = []
    if shadow_only:
        blockers.extend(shadow_evidence_blockers)
    else:
        advisory_blockers.extend(shadow_evidence_blockers)

    ready_for_partial = not blockers and shadow_only

    if not enabled:
        status = "disabled"
    elif entry is None:
        status = "not_in_universe"
    elif tier == "secondary" and not secondary_live_enabled:
        status = "secondary_shadow_only"
    elif tier == "core" and core_live_slots > 0 and core_live_rank > core_live_slots:
        status = "outside_current_core_live_window"
    elif shadow_only:
        if not available:
            status = "shadow_unavailable"
        elif recent_closed <= 0:
            status = "waiting_fresh_setup"
        elif ready_for_partial:
            status = "shadow_ready_for_partial"
        elif blockers:
            status = "shadow_collecting"
        else:
            status = "shadow_collecting"
    elif advisory_blockers:
        status = "live_bootstrap_collecting"
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
        advisory_blockers=tuple(advisory_blockers),
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
            "core_live_rank": int(core_live_rank),
            "secondary_live_enabled": secondary_live_enabled,
            "shadow_evidence_policy": "hard_gate_in_shadow_only_advisory_in_live_enabled",
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
        "advisory_blockers": list(payload.advisory_blockers),
        "shadow_metrics": dict(payload.shadow_metrics),
    }
