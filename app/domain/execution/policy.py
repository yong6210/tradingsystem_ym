from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.enums import ExecutionMode


@dataclass(frozen=True, slots=True)
class RolloutPolicy:
    strategy_family: str
    live_enabled: bool
    max_execution_mode: ExecutionMode
    max_risk_r: float
    allowed_sessions: tuple[str, ...]
    min_quality_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_family": self.strategy_family,
            "live_enabled": bool(self.live_enabled),
            "max_execution_mode": self.max_execution_mode.value,
            "max_risk_r": float(self.max_risk_r),
            "allowed_sessions": list(self.allowed_sessions),
            "min_quality_score": float(self.min_quality_score),
        }
