from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FastFailurePolicy:
    max_bars: int
    stop_r: float
    stop_price: float
    policy_name: str
    requires_sl_touch: bool


def _price_tolerance(value: float) -> float:
    return max(abs(float(value)) * 0.0005, 1e-6)


def resolve_fast_failure_policy(*, plan: Any, held_bars: int) -> FastFailurePolicy | None:
    validity = dict(getattr(plan, "validity", {}) or {})
    enabled = bool(validity.get("strategy_fast_failure_enabled", False))
    max_bars = int(validity.get("strategy_fast_failure_max_bars", 0) or 0)
    stop_r = float(validity.get("strategy_fast_failure_stop_r", 0.0) or 0.0)
    policy_name = str(validity.get("strategy_fast_failure_policy") or "initial_guard_stop").strip() or "initial_guard_stop"
    requires_sl_touch = bool(validity.get("strategy_fast_failure_requires_sl_touch", False))
    if not enabled or max_bars <= 0 or held_bars <= 0 or held_bars > max_bars:
        return None
    if stop_r <= 0.0 or stop_r >= 1.0:
        return None

    entry_price = float(getattr(plan, "entry_price", 0.0) or 0.0)
    stop_loss = float(getattr(plan, "sl", 0.0) or 0.0)
    risk_abs = abs(entry_price - stop_loss)
    if risk_abs <= 1e-9:
        return None

    direction = str(getattr(plan, "direction", "") or "").lower()
    if direction == "short":
        stop_price = entry_price + (risk_abs * stop_r)
    else:
        stop_price = entry_price - (risk_abs * stop_r)
    return FastFailurePolicy(
        max_bars=max_bars,
        stop_r=stop_r,
        stop_price=float(stop_price),
        policy_name=policy_name,
        requires_sl_touch=requires_sl_touch,
    )


def fast_failure_hit(*, plan: Any, policy: FastFailurePolicy, high: float, low: float) -> bool:
    direction = str(getattr(plan, "direction", "") or "").lower()
    if direction == "short":
        return float(high) >= float(policy.stop_price) - _price_tolerance(policy.stop_price)
    return float(low) <= float(policy.stop_price) + _price_tolerance(policy.stop_price)


def fast_failure_trigger_detail(*, plan: Any, policy: FastFailurePolicy, held_bars: int) -> dict[str, Any]:
    return {
        "policy": policy.policy_name,
        "guard_type": "initial_stop",
        "max_bars": int(policy.max_bars),
        "actual_held_bars": int(held_bars),
        "stop_r": round(float(policy.stop_r), 8),
        "guard_stop_price": round(float(policy.stop_price), 8),
        "requires_sl_touch": bool(policy.requires_sl_touch),
        "entry_price": float(getattr(plan, "entry_price", 0.0) or 0.0),
        "original_stop_price": float(getattr(plan, "sl", 0.0) or 0.0),
        "saved_r_vs_full_stop": round(max(0.0, 1.0 - float(policy.stop_r)), 8),
    }
