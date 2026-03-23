from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.core.enums import EntryModel
from app.db.models import Zone
from app.services.context_engine import ContextSnapshot


@dataclass
class EntryDecision:
    model: EntryModel
    reason: str


class EntryModelRouter:
    def __init__(self):
        self.settings = get_settings()

    def choose(
        self,
        zone: Zone,
        context: ContextSnapshot,
        zone_strength: float,
        near_lp: bool,
        confluence_score: float | None = None,
    ) -> EntryDecision:
        counter_trend = (zone.dir_bias == "support" and context.v < 0 and context.regime_15m > 0.65) or (
            zone.dir_bias == "resistance" and context.v > 0 and context.regime_15m > 0.65
        )
        conservative = confluence_score is not None and confluence_score < (self.settings.min_confluence_score + 6.0)

        if near_lp and (context.friction_5m >= 0.35 or conservative):
            return EntryDecision(
                model=EntryModel.SWEEP_CONFIRM,
                reason="lp_nearby_and_sweep_risk",
            )

        if (
            context.friction_5m > 0.5
            or context.jump_rate_5m > 0.25
            or counter_trend
            or zone_strength < 60
            or conservative
        ):
            return EntryDecision(model=EntryModel.CONFIRM, reason="friction_or_counter_trend")

        if zone.width_atr <= 0.6 and zone_strength >= 65 and (confluence_score or 0.0) >= 75.0:
            return EntryDecision(model=EntryModel.LIMIT, reason="high_quality_narrow_zone")

        return EntryDecision(model=EntryModel.CONFIRM, reason="default_safe_mode")
