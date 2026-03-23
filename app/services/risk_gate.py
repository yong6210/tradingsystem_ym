from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.core.enums import RiskGateState


@dataclass(slots=True)
class RiskSnapshot:
    state: RiskGateState
    reasons: list[str]
    consecutive_losses: int
    jump_rate: float
    infra_healthy: bool


def evaluate_risk_gate(
    *,
    consecutive_losses: int,
    jump_rate: float,
    infra_healthy: bool,
    settings: Settings,
) -> RiskSnapshot:
    reasons: list[str] = []

    if not infra_healthy:
        reasons.append("infra-unhealthy")
        return RiskSnapshot(
            state=RiskGateState.CLOSED,
            reasons=reasons,
            consecutive_losses=consecutive_losses,
            jump_rate=jump_rate,
            infra_healthy=infra_healthy,
        )

    if consecutive_losses >= settings.max_consecutive_losses:
        reasons.append("consecutive-loss-limit")
        return RiskSnapshot(
            state=RiskGateState.CLOSED,
            reasons=reasons,
            consecutive_losses=consecutive_losses,
            jump_rate=jump_rate,
            infra_healthy=infra_healthy,
        )

    if jump_rate >= settings.jump_rate_gate:
        reasons.append("jump-rate-limit")
        return RiskSnapshot(
            state=RiskGateState.THROTTLED,
            reasons=reasons,
            consecutive_losses=consecutive_losses,
            jump_rate=jump_rate,
            infra_healthy=infra_healthy,
        )

    return RiskSnapshot(
        state=RiskGateState.OPEN,
        reasons=["normal"],
        consecutive_losses=consecutive_losses,
        jump_rate=jump_rate,
        infra_healthy=infra_healthy,
    )


@dataclass(slots=True)
class RiskGateInput:
    consecutive_losses: int
    jump_rate: float
    api_healthy: bool


@dataclass(slots=True)
class RiskGateOutput:
    state: RiskGateState
    can_open_new_trade: bool
    reason: str


class RiskGate:
    """Class wrapper for engine-level kill switch policy."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def evaluate(self, payload: RiskGateInput) -> RiskGateOutput:
        if not payload.api_healthy:
            return RiskGateOutput(
                state=RiskGateState.CLOSED,
                can_open_new_trade=False,
                reason="api_unhealthy",
            )

        # Hard stop on sustained loss streak.
        if payload.consecutive_losses >= self.settings.max_consecutive_losses:
            return RiskGateOutput(
                state=RiskGateState.CLOSED,
                can_open_new_trade=False,
                reason="max_consecutive_losses",
            )

        if payload.jump_rate >= self.settings.jump_rate_gate:
            return RiskGateOutput(
                state=RiskGateState.THROTTLED,
                can_open_new_trade=False,
                reason="jump_rate_over_limit",
            )

        return RiskGateOutput(
            state=RiskGateState.OPEN,
            can_open_new_trade=True,
            reason="normal",
        )
