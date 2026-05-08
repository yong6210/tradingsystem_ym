from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import StrategyMode


@dataclass(slots=True)
class StrategyModePolicy:
    mode: StrategyMode
    allowed_families: tuple[str, ...]
    allowed_grades: tuple[str, ...]
    max_daily_trades: int
    max_total_risk_r: float
    shadow_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "allowed_families": list(self.allowed_families),
            "allowed_grades": list(self.allowed_grades),
            "max_daily_trades": int(self.max_daily_trades),
            "max_total_risk_r": float(self.max_total_risk_r),
            "shadow_only": bool(self.shadow_only),
        }


class StrategyModeService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def current_mode(self) -> StrategyMode:
        value = getattr(self.settings, "strategy_mode", StrategyMode.A_ONLY)
        if isinstance(value, StrategyMode):
            return value
        try:
            return StrategyMode(str(value).upper())
        except ValueError:
            return StrategyMode.A_ONLY

    def policy(self, mode: StrategyMode | None = None) -> StrategyModePolicy:
        active = mode or self.current_mode()
        if active == StrategyMode.A_PLUS_B:
            return StrategyModePolicy(
                mode=active,
                allowed_families=("sweep_reversal", "trend_continuation", "session_impulse_retest"),
                allowed_grades=("A", "B"),
                max_daily_trades=int(self.settings.strategy_mode_a_plus_b_max_daily_trades),
                max_total_risk_r=float(self.settings.strategy_mode_a_plus_b_max_total_risk_r),
            )
        if active == StrategyMode.RESEARCH:
            return StrategyModePolicy(
                mode=active,
                allowed_families=("sweep_reversal", "trend_continuation", "range_rotation", "session_impulse_retest"),
                allowed_grades=("A", "B", "C"),
                max_daily_trades=int(self.settings.strategy_mode_research_max_daily_trades),
                max_total_risk_r=float(self.settings.strategy_mode_research_max_total_risk_r),
                shadow_only=True,
            )
        return StrategyModePolicy(
            mode=StrategyMode.A_ONLY,
            allowed_families=("sweep_reversal", "trend_continuation", "session_impulse_retest"),
            allowed_grades=("A",),
            max_daily_trades=int(self.settings.strategy_mode_a_only_max_daily_trades),
            max_total_risk_r=float(self.settings.strategy_mode_a_only_max_total_risk_r),
        )

    def allow_candidate(
        self,
        *,
        strategy_family: str | None,
        strategy_grade: str | None,
        mode: StrategyMode | None = None,
    ) -> tuple[bool, str | None]:
        policy = self.policy(mode)
        family = str(strategy_family or "").strip()
        grade = str(strategy_grade or "").strip().upper()
        if not family or family == "legacy_zone_plan":
            return True, None
        if family not in policy.allowed_families:
            return False, "mode_family_not_allowed"
        if grade not in policy.allowed_grades:
            return False, "mode_grade_not_allowed"
        return True, None

    def apply_to_sizing(self, sizing: dict[str, Any], *, mode: StrategyMode | None = None) -> dict[str, Any]:
        policy = self.policy(mode)
        out = dict(sizing)
        out["strategy_mode"] = policy.mode.value
        out["shadow_only"] = bool(policy.shadow_only)
        out["mode_policy"] = policy.to_dict()
        if not policy.shadow_only:
            return out
        out["final_risk_r"] = 0.0
        out["blocked"] = True
        out["blocked_reason"] = "mode_shadow_only"
        notes = dict(out.get("notes") or {})
        notes["mode"] = "mode_shadow_only"
        out["notes"] = notes
        return out

    def daily_limit_reached(self, *, today_trade_count: int, accepted_candidates: int = 0, mode: StrategyMode | None = None) -> bool:
        policy = self.policy(mode)
        return int(today_trade_count) + int(accepted_candidates) >= int(policy.max_daily_trades)

    def projected_total_risk_exceeded(
        self,
        *,
        current_total_risk_r: float,
        candidate_risk_r: float,
        mode: StrategyMode | None = None,
    ) -> bool:
        policy = self.policy(mode)
        return float(current_total_risk_r) + float(candidate_risk_r) > float(policy.max_total_risk_r) + 1e-9
