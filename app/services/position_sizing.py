from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import EntryModel


@dataclass(slots=True)
class PositionSizingInput:
    strategy_family: str
    strategy_grade: str | None
    regime: str
    reaction_classification: str
    confirm_only: bool
    entry_model: str
    active_thesis_clusters: int
    transition_state: str = "none"
    symbol: str = ""
    direction: str = ""


class PositionSizingService:
    """Compute the v2 recommended risk sizing contract in R units."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def evaluate(self, payload: PositionSizingInput) -> dict[str, Any]:
        grade = str(payload.strategy_grade or "B").upper()
        family = str(payload.strategy_family or "legacy_zone_plan").lower()
        regime = str(payload.regime or "range").lower()
        reaction = str(payload.reaction_classification or "not_applicable").lower()
        transition_state = str(payload.transition_state or "none").lower()

        grade_risk = self._grade_risk(grade)
        regime_factor, regime_reason = self._regime_factor(regime=regime, transition_state=transition_state)
        reaction_factor, reaction_reason = self._reaction_factor(
            reaction_classification=reaction,
            confirm_only=bool(payload.confirm_only),
        )
        thesis_factor, thesis_reason = self._thesis_factor(int(payload.active_thesis_clusters))
        execution_factor = self._execution_factor(str(payload.entry_model or EntryModel.CONFIRM.value))
        direction_factor, direction_reason = self._direction_factor(
            symbol=str(payload.symbol or ""),
            strategy_family=family,
            direction=str(payload.direction or ""),
        )

        final_risk_r = round(
            grade_risk * regime_factor * reaction_factor * thesis_factor * execution_factor * direction_factor,
            4,
        )
        blocked_reason = regime_reason or reaction_reason or thesis_reason

        return {
            "schema_version": "v2",
            "strategy_family": family,
            "strategy_grade": grade,
            "grade_source": "strategy_grade" if grade in {"A", "B", "C"} and payload.strategy_grade is not None else "legacy_default_b",
            "symbol": str(payload.symbol or ""),
            "direction": str(payload.direction or ""),
            "active_thesis_clusters": int(payload.active_thesis_clusters),
            "transition_state": transition_state,
            "reaction_classification": reaction,
            "confirm_only": bool(payload.confirm_only),
            "entry_model": str(payload.entry_model),
            "factors": {
                "grade_risk": round(grade_risk, 4),
                "regime_factor": round(regime_factor, 4),
                "reaction_factor": round(reaction_factor, 4),
                "thesis_factor": round(thesis_factor, 4),
                "execution_factor": round(execution_factor, 4),
                "direction_factor": round(direction_factor, 4),
            },
            "final_risk_r": final_risk_r,
            "blocked": final_risk_r <= 0.0,
            "blocked_reason": blocked_reason,
            "notes": {
                "regime": regime_reason,
                "reaction": reaction_reason,
                "thesis": thesis_reason,
                "direction": direction_reason,
            },
        }

    def evaluate_from_row(self, row: dict[str, Any], *, active_thesis_clusters: int) -> dict[str, Any]:
        validity = dict(row.get("validity") or {})
        return self.evaluate(
            PositionSizingInput(
                strategy_family=str(row.get("strategy_family") or validity.get("strategy_family", "legacy_zone_plan")),
                strategy_grade=validity.get("strategy_grade") or row.get("strategy_grade"),
                regime=str(row.get("regime") or validity.get("regime", "range")),
                reaction_classification=str(validity.get("reaction_classification", "not_applicable")),
                confirm_only=bool(validity.get("strategy_family_confirm_only", False)),
                entry_model=str(row.get("entry_model") or validity.get("entry_model", EntryModel.CONFIRM.value)),
                active_thesis_clusters=active_thesis_clusters,
                transition_state=str(validity.get("transition_state", "none")),
                symbol=str(row.get("symbol") or validity.get("symbol", "")),
                direction=str(row.get("direction") or validity.get("direction", "")),
            )
        )

    def _grade_risk(self, grade: str) -> float:
        if grade == "A":
            return float(self.settings.sizing_grade_a_r)
        if grade == "B":
            return float(self.settings.sizing_grade_b_r)
        if grade == "C":
            return float(self.settings.sizing_grade_c_r)
        return 0.0

    def _regime_factor(self, *, regime: str, transition_state: str) -> tuple[float, str | None]:
        if transition_state in {"transition_confirmed", "transition_watch"} or regime == "transition":
            return float(self.settings.sizing_regime_factor_transition), "transition_zero_risk"
        if regime == "trend":
            return float(self.settings.sizing_regime_factor_trend), None
        if regime == "shock":
            return float(self.settings.sizing_regime_factor_shock), "shock_size_clamp"
        return float(self.settings.sizing_regime_factor_range), None

    def _reaction_factor(self, *, reaction_classification: str, confirm_only: bool) -> tuple[float, str | None]:
        if reaction_classification == "mixed":
            return float(self.settings.sizing_reaction_factor_mixed), "mixed_zero_risk"
        if confirm_only:
            return float(self.settings.sizing_reaction_factor_confirm_only), "confirm_only_size_clamp"
        if reaction_classification.endswith("tentative"):
            return float(self.settings.sizing_reaction_factor_confirm_only), "tentative_reaction_size_clamp"
        return float(self.settings.sizing_reaction_factor_confirmed), None

    def _thesis_factor(self, active_thesis_clusters: int) -> tuple[float, str | None]:
        if active_thesis_clusters >= 2:
            return float(self.settings.sizing_thesis_factor_two_or_more), "thesis_cluster_cap_zero_risk"
        if active_thesis_clusters == 1:
            return float(self.settings.sizing_thesis_factor_one_active), "active_thesis_size_clamp"
        return float(self.settings.sizing_thesis_factor_none), None

    def _execution_factor(self, entry_model: str) -> float:
        if entry_model == EntryModel.LIMIT.value:
            return float(self.settings.sizing_execution_factor_limit)
        if entry_model == EntryModel.SWEEP_CONFIRM.value:
            return float(self.settings.sizing_execution_factor_sweep_confirm)
        return float(self.settings.sizing_execution_factor_confirm)

    def _direction_factor(self, *, symbol: str, strategy_family: str, direction: str) -> tuple[float, str | None]:
        normalized_symbol = str(symbol or "").strip().upper()
        normalized_family = str(strategy_family or "").strip().lower()
        normalized_direction = str(direction or "").strip().upper()
        if (
            normalized_symbol == "BTCUSDC"
            and normalized_family == "sweep_reversal"
            and normalized_direction == "LONG"
        ):
            factor = float(self.settings.sizing_btc_sweep_reversal_long_factor)
            reason = "btc_sweep_reversal_long_size_clamp" if factor < 1.0 else None
            return factor, reason
        return 1.0, None
