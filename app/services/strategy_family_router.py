from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import EntryModel
from app.db.models import Candle, Zone
from app.services.acceptance_rejection_classifier import AcceptanceRejectionResult
from app.services.common import clamp
from app.services.context_engine import ContextSnapshot


@dataclass(slots=True)
class StrategyFamilyDecision:
    available: bool
    family: str
    grade: str
    score: float
    reason: str
    entry_model: EntryModel | None
    components: dict[str, float] = field(default_factory=dict)
    clean_case: bool = False
    confirm_only: bool = False
    split: dict[str, float] = field(default_factory=dict)
    time_stop_min_bars: int = 0
    time_stop_max_bars: int = 0
    scorecard: dict[str, Any] = field(default_factory=dict)


class StrategyFamilyRouter:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @staticmethod
    def _round_scores(values: dict[str, float]) -> dict[str, float]:
        return {key: round(float(value), 2) for key, value in values.items()}

    def _grade_thresholds(self, family: str) -> dict[str, float]:
        if family == "sweep_reversal":
            return {
                "A": float(self.settings.sweep_reversal_grade_a_score),
                "B": float(self.settings.sweep_reversal_grade_b_score),
                "C": float(self.settings.sweep_reversal_grade_c_score),
            }
        if family == "trend_continuation":
            return {
                "A": float(self.settings.trend_continuation_grade_a_score),
                "B": float(self.settings.trend_continuation_grade_b_score),
                "C": float(self.settings.trend_continuation_grade_c_score),
            }
        if family == "range_rotation":
            return {
                "A": float(self.settings.range_rotation_grade_a_score),
                "B": float(self.settings.range_rotation_grade_b_score),
                "C": float(self.settings.range_rotation_grade_c_score),
            }
        return {"A": 0.0, "B": 0.0, "C": 0.0}

    @staticmethod
    def _bucket_caps(family: str) -> dict[str, float]:
        if family == "sweep_reversal":
            return {
                "location": 30.0,
                "liquidity": 20.0,
                "reaction": 35.0,
                "invalidation": 10.0,
                "session": 5.0,
                "trendline_bonus": 2.0,
            }
        if family == "trend_continuation":
            return {
                "location": 35.0,
                "liquidity": 10.0,
                "reaction": 40.0,
                "invalidation": 10.0,
                "session": 5.0,
                "trendline_bonus": 2.0,
            }
        if family == "range_rotation":
            return {
                "location": 40.0,
                "liquidity": 20.0,
                "reaction": 15.0,
                "invalidation": 20.0,
                "session": 5.0,
                "trendline_bonus": 2.0,
            }
        return {
            "location": 0.0,
            "liquidity": 0.0,
            "reaction": 0.0,
            "invalidation": 0.0,
            "session": 0.0,
            "trendline_bonus": 2.0,
        }

    def _build_scorecard(
        self,
        *,
        family: str,
        grade: str,
        raw_components: dict[str, float],
        buckets: dict[str, float],
        trendline_bonus: float = 0.0,
    ) -> dict[str, Any]:
        rounded_raw = self._round_scores(raw_components)
        rounded_buckets = self._round_scores(buckets)
        rounded_buckets["trendline_bonus"] = round(float(trendline_bonus), 2)
        score_ex_trendline = round(sum(rounded_raw.values()), 2)
        score_total = round(score_ex_trendline + rounded_buckets["trendline_bonus"], 2)
        return {
            "schema_version": "v2",
            "family": family,
            "grade": grade,
            "score": score_total,
            "score_ex_trendline": score_ex_trendline,
            "grade_thresholds": self._grade_thresholds(family),
            "bucket_caps": self._bucket_caps(family),
            "buckets": rounded_buckets,
            "raw_components": rounded_raw,
            # Trendline is explicit bonus-only until a dedicated detector exists.
            "trendline_bonus_source": "disabled_until_trendline_detector",
        }

    def route(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        reaction: AcceptanceRejectionResult,
        near_lp: bool,
        zone_strength: float,
        confluence_score: float,
        regime_name: str,
        candles_5m: list[Candle] | None = None,
    ) -> StrategyFamilyDecision:
        classification = str(reaction.classification)
        if reaction.available and classification in {"rejection_confirmed", "rejection_tentative"}:
            sweep = self._route_sweep_reversal(
                zone=zone,
                context=context,
                reaction=reaction,
                near_lp=near_lp,
                zone_strength=zone_strength,
                confluence_score=confluence_score,
                regime_name=regime_name,
            )
            if sweep.available or regime_name != "range":
                return sweep
            range_rotation = self._route_range_rotation(
                zone=zone,
                context=context,
                reaction=reaction,
                near_lp=near_lp,
                zone_strength=zone_strength,
                confluence_score=confluence_score,
                regime_name=regime_name,
            )
            if range_rotation.family != "none":
                return range_rotation
            return sweep
        return self._route_trend_continuation(
            zone=zone,
            context=context,
            near_lp=near_lp,
            zone_strength=zone_strength,
            confluence_score=confluence_score,
            regime_name=regime_name,
            candles_5m=candles_5m,
        )

    def _route_sweep_reversal(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        reaction: AcceptanceRejectionResult,
        near_lp: bool,
        zone_strength: float,
        confluence_score: float,
        regime_name: str,
    ) -> StrategyFamilyDecision:
        classification = str(reaction.classification)
        if not reaction.available or classification not in {"rejection_confirmed", "rejection_tentative"}:
            return StrategyFamilyDecision(
                available=False,
                family="none",
                grade="F",
                score=0.0,
                reason="reaction_not_rejection",
                entry_model=None,
            )

        counter_trend = (zone.dir_bias == "support" and context.v < 0) or (zone.dir_bias == "resistance" and context.v > 0)
        reaction_input = dict(reaction.input or {})
        session_quality_raw = float(reaction_input.get("session_quality", 0.0))
        outside_close_count = int(reaction_input.get("outside_close_count", 99))

        location_score = 20.0 if zone.type == "LP" else 18.0 if near_lp else 12.0
        if regime_name == "trend" and not (near_lp or zone.type == "LP"):
            location_score = min(location_score, 8.0)

        sweep_quality_score = 20.0 if classification == "rejection_confirmed" else 16.0
        reaction_quality_score = clamp(reaction.rejection_score / 5.0, 0.0, 20.0)

        score_gap = reaction.rejection_score - reaction.acceptance_score
        if score_gap >= 25.0:
            clarity_score = 15.0
        elif score_gap >= 18.0:
            clarity_score = 13.0
        elif score_gap >= 12.0:
            clarity_score = 11.0
        elif score_gap >= 7.0:
            clarity_score = 8.0
        else:
            clarity_score = 4.0

        if regime_name == "range":
            htf_alignment_score = 10.0
        elif regime_name == "trend":
            htf_alignment_score = 7.0 if near_lp or zone.type == "LP" else 3.0
            if counter_trend:
                htf_alignment_score = max(4.0, htf_alignment_score - 1.0)
        elif regime_name == "shock":
            htf_alignment_score = 6.0 if classification == "rejection_confirmed" else 3.0
        else:
            htf_alignment_score = 5.0 if classification == "rejection_confirmed" else 2.0

        execution_zone_quality_score = clamp(zone_strength / 10.0, 0.0, 10.0)
        execution_zone_quality_score -= max(0.0, zone.width_atr - 0.55) * 10.0
        execution_zone_quality_score = clamp(execution_zone_quality_score, 0.0, 10.0)

        session_quality_score = clamp(session_quality_raw * 5.0, 0.0, 5.0)

        components = {
            "location": round(location_score, 2),
            "sweep_quality": round(sweep_quality_score, 2),
            "reaction_quality": round(reaction_quality_score, 2),
            "clarity": round(clarity_score, 2),
            "htf_alignment": round(htf_alignment_score, 2),
            "execution_zone_quality": round(execution_zone_quality_score, 2),
            "session_quality": round(session_quality_score, 2),
        }
        scorecard = self._build_scorecard(
            family="sweep_reversal",
            grade=self._grade_sweep_reversal(sum(components.values())),
            raw_components=components,
            buckets={
                "location": location_score + htf_alignment_score,
                "liquidity": sweep_quality_score,
                "reaction": reaction_quality_score + clarity_score,
                "invalidation": execution_zone_quality_score,
                "session": session_quality_score,
            },
            trendline_bonus=0.0,
        )
        family_score = round(sum(components.values()), 2)
        grade = self._grade_sweep_reversal(family_score)
        scorecard["grade"] = grade
        scorecard["score"] = family_score
        scorecard["score_ex_trendline"] = family_score

        if family_score < self.settings.sweep_reversal_min_score:
            return StrategyFamilyDecision(
                available=False,
                family="sweep_reversal",
                grade=grade,
                score=family_score,
                reason="sweep_reversal_score_below_threshold",
                entry_model=None,
                components=components,
                scorecard=scorecard,
            )
        if regime_name == "trend" and not (near_lp or zone.type == "LP"):
            return StrategyFamilyDecision(
                available=False,
                family="sweep_reversal",
                grade=grade,
                score=family_score,
                reason="trend_requires_extreme_location",
                entry_model=None,
                components=components,
                scorecard=scorecard,
            )
        if regime_name == "shock" and not (grade == "A" and classification == "rejection_confirmed"):
            return StrategyFamilyDecision(
                available=False,
                family="sweep_reversal",
                grade=grade,
                score=family_score,
                reason="shock_requires_a_grade_rejection",
                entry_model=None,
                components=components,
                scorecard=scorecard,
            )
        if context.transition_state == "transition_watch" and grade != "A":
            return StrategyFamilyDecision(
                available=False,
                family="sweep_reversal",
                grade=grade,
                score=family_score,
                reason="transition_watch_a_only",
                entry_model=None,
                components=components,
                scorecard=scorecard,
            )

        clean_case = (
            classification == "rejection_confirmed"
            and grade == "A"
            and zone.width_atr <= self.settings.sweep_reversal_clean_limit_max_width_atr
            and context.friction_5m <= self.settings.sweep_reversal_clean_limit_max_friction
            and context.jump_rate_5m <= self.settings.sweep_reversal_clean_limit_max_jump_rate
            and outside_close_count <= self.settings.reaction_classifier_rejection_max_outside_closes
            and regime_name not in {"shock", "transition"}
            and context.transition_state != "transition_watch"
        )

        if grade == "A":
            entry_model = EntryModel.LIMIT if clean_case else EntryModel.SWEEP_CONFIRM
        else:
            entry_model = EntryModel.CONFIRM

        confirm_only = (
            classification == "rejection_tentative"
            or context.transition_state == "transition_watch"
            or regime_name == "shock"
            or grade in {"B", "C"}
        )
        if confirm_only:
            entry_model = EntryModel.CONFIRM

        reason = "sweep_reversal_confirm_only" if confirm_only else "sweep_reversal_limit" if clean_case else "sweep_reversal_sweep_confirm"
        return StrategyFamilyDecision(
            available=True,
            family="sweep_reversal",
            grade=grade,
            score=family_score,
            reason=reason,
            entry_model=entry_model,
            components=components,
            clean_case=clean_case,
            confirm_only=confirm_only,
            split={"tp1": 0.4, "tp2": 0.4, "runner": 0.2},
            time_stop_min_bars=3,
            time_stop_max_bars=5,
            scorecard=scorecard,
        )

    def _route_trend_continuation(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        near_lp: bool,
        zone_strength: float,
        confluence_score: float,
        regime_name: str,
        candles_5m: list[Candle] | None,
    ) -> StrategyFamilyDecision:
        if regime_name != "trend":
            return StrategyFamilyDecision(
                available=False,
                family="none",
                grade="F",
                score=0.0,
                reason="trend_continuation_not_applicable",
                entry_model=None,
            )
        if zone.type not in {"OB", "FVG"}:
            return StrategyFamilyDecision(
                available=False,
                family="none",
                grade="F",
                score=0.0,
                reason="trend_continuation_zone_not_supported",
                entry_model=None,
            )

        long_setup = zone.dir_bias == "support"
        short_setup = zone.dir_bias == "resistance"
        aligned = (long_setup and context.v > 0 and context.sdir > -0.05) or (
            short_setup and context.v < 0 and context.sdir < 0.05
        )
        if not aligned:
            return StrategyFamilyDecision(
                available=False,
                family="none",
                grade="F",
                score=0.0,
                reason="trend_continuation_direction_misaligned",
                entry_model=None,
            )

        if not candles_5m or len(candles_5m) < 8:
            return StrategyFamilyDecision(
                available=False,
                family="trend_continuation",
                grade="F",
                score=0.0,
                reason="trend_continuation_insufficient_candles",
                entry_model=None,
            )

        dist_atr = abs(context.last_price - zone.mid) / max(context.atr15, 1e-9)
        if dist_atr > 1.8:
            return StrategyFamilyDecision(
                available=False,
                family="none",
                grade="F",
                score=0.0,
                reason="trend_continuation_pullback_not_ready",
                entry_model=None,
            )

        recent = candles_5m[-8:]
        impulse_window = recent[:-3]
        pullback_window = recent[-3:]
        if len(impulse_window) < 3:
            return StrategyFamilyDecision(
                available=False,
                family="trend_continuation",
                grade="F",
                score=0.0,
                reason="trend_continuation_insufficient_impulse",
                entry_model=None,
            )

        if long_setup:
            impulse_atr = (impulse_window[-1].c - impulse_window[0].o) / max(context.atr5, 1e-9)
            impulse_peak = max(candle.h for candle in impulse_window)
            pullback_extreme = min(candle.l for candle in pullback_window)
            pullback_depth_atr = (impulse_peak - pullback_extreme) / max(context.atr5, 1e-9)
            protected_level_held = min(candle.l for candle in recent[-4:]) >= zone.low - self.settings.trend_continuation_protected_buffer_atr * context.atr5
            counter_closes = sum(1 for index in range(1, len(pullback_window)) if pullback_window[index].c <= pullback_window[index - 1].c)
            current_side_valid = context.last_price >= zone.low - self.settings.trend_continuation_protected_buffer_atr * context.atr5
        else:
            impulse_atr = (impulse_window[0].o - impulse_window[-1].c) / max(context.atr5, 1e-9)
            impulse_peak = min(candle.l for candle in impulse_window)
            pullback_extreme = max(candle.h for candle in pullback_window)
            pullback_depth_atr = (pullback_extreme - impulse_peak) / max(context.atr5, 1e-9)
            protected_level_held = max(candle.h for candle in recent[-4:]) <= zone.high + self.settings.trend_continuation_protected_buffer_atr * context.atr5
            counter_closes = sum(1 for index in range(1, len(pullback_window)) if pullback_window[index].c >= pullback_window[index - 1].c)
            current_side_valid = context.last_price <= zone.high + self.settings.trend_continuation_protected_buffer_atr * context.atr5

        candidate_detected = current_side_valid and counter_closes >= 1
        if not candidate_detected:
            return StrategyFamilyDecision(
                available=False,
                family="none",
                grade="F",
                score=0.0,
                reason="trend_continuation_pullback_not_detected",
                entry_model=None,
            )

        htf_trend_clarity_score = clamp(context.regime_15m * 16.0 + (4.0 if aligned else 0.0), 0.0, 20.0)
        if impulse_atr >= 2.0:
            impulse_quality_score = 20.0
        elif impulse_atr >= self.settings.trend_continuation_min_impulse_atr:
            impulse_quality_score = 16.0
        elif impulse_atr >= 0.9:
            impulse_quality_score = 12.0
        elif impulse_atr >= 0.6:
            impulse_quality_score = 8.0
        else:
            impulse_quality_score = 0.0

        if counter_closes >= 2 and self.settings.trend_continuation_pullback_min_atr <= pullback_depth_atr <= 1.1:
            pullback_quality_score = 20.0
        elif counter_closes >= 1 and self.settings.trend_continuation_pullback_min_atr <= pullback_depth_atr <= self.settings.trend_continuation_pullback_max_atr:
            pullback_quality_score = 16.0
        elif counter_closes >= 1 and pullback_depth_atr <= self.settings.trend_continuation_pullback_max_atr + 0.4:
            pullback_quality_score = 10.0
        else:
            pullback_quality_score = 0.0

        protected_score = 15.0 if protected_level_held else 0.0
        execution_zone_freshness_score = clamp(
            10.0 - max(0.0, zone.width_atr - 0.5) * 8.0 - max(0, zone.touch_count - 1) * 2.5,
            0.0,
            10.0,
        )
        liquidity_path_clarity_score = clamp(confluence_score / 10.0 - (2.0 if near_lp else 0.0), 0.0, 10.0)
        session_quality_score = clamp((1.0 - (0.7 * context.friction_5m + 0.3 * context.jump_rate_5m)) * 5.0, 0.0, 5.0)

        components = {
            "htf_trend_clarity": round(htf_trend_clarity_score, 2),
            "impulse_quality": round(impulse_quality_score, 2),
            "pullback_quality": round(pullback_quality_score, 2),
            "protected_level_hold": round(protected_score, 2),
            "execution_zone_freshness": round(execution_zone_freshness_score, 2),
            "liquidity_path_clarity": round(liquidity_path_clarity_score, 2),
            "session_quality": round(session_quality_score, 2),
        }
        scorecard = self._build_scorecard(
            family="trend_continuation",
            grade=self._grade_trend_continuation(sum(components.values())),
            raw_components=components,
            buckets={
                "location": htf_trend_clarity_score + protected_score,
                "liquidity": liquidity_path_clarity_score,
                "reaction": impulse_quality_score + pullback_quality_score,
                "invalidation": execution_zone_freshness_score,
                "session": session_quality_score,
            },
            trendline_bonus=0.0,
        )
        family_score = round(sum(components.values()), 2)
        grade = self._grade_trend_continuation(family_score)
        scorecard["grade"] = grade
        scorecard["score"] = family_score
        scorecard["score_ex_trendline"] = family_score

        if impulse_atr < self.settings.trend_continuation_min_impulse_atr:
            return StrategyFamilyDecision(
                available=False,
                family="trend_continuation",
                grade=grade,
                score=family_score,
                reason="trend_continuation_weak_impulse",
                entry_model=None,
                components=components,
                scorecard=scorecard,
            )
        if not protected_level_held:
            return StrategyFamilyDecision(
                available=False,
                family="trend_continuation",
                grade=grade,
                score=family_score,
                reason="trend_continuation_protected_level_broken",
                entry_model=None,
                components=components,
                scorecard=scorecard,
            )
        if pullback_depth_atr < self.settings.trend_continuation_pullback_min_atr or pullback_depth_atr > self.settings.trend_continuation_pullback_max_atr:
            return StrategyFamilyDecision(
                available=False,
                family="trend_continuation",
                grade=grade,
                score=family_score,
                reason="trend_continuation_pullback_invalid",
                entry_model=None,
                components=components,
                scorecard=scorecard,
            )
        if family_score < self.settings.trend_continuation_min_score:
            return StrategyFamilyDecision(
                available=False,
                family="trend_continuation",
                grade=grade,
                score=family_score,
                reason="trend_continuation_score_below_threshold",
                entry_model=None,
                components=components,
                scorecard=scorecard,
            )

        entry_model = EntryModel.LIMIT if grade == "A" else EntryModel.CONFIRM
        confirm_only = grade in {"B", "C"}
        reason = "trend_continuation_limit" if entry_model == EntryModel.LIMIT else "trend_continuation_confirm_only"
        return StrategyFamilyDecision(
            available=True,
            family="trend_continuation",
            grade=grade,
            score=family_score,
            reason=reason,
            entry_model=entry_model,
            components=components,
            clean_case=grade == "A",
            confirm_only=confirm_only,
            split={"tp1": 0.3, "tp2": 0.3, "runner": 0.4},
            time_stop_min_bars=5,
            time_stop_max_bars=8,
            scorecard=scorecard,
        )

    def _route_range_rotation(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        reaction: AcceptanceRejectionResult,
        near_lp: bool,
        zone_strength: float,
        confluence_score: float,
        regime_name: str,
    ) -> StrategyFamilyDecision:
        if regime_name != "range":
            return StrategyFamilyDecision(
                available=False,
                family="none",
                grade="F",
                score=0.0,
                reason="range_rotation_not_applicable",
                entry_model=None,
            )
        if not reaction.available or str(reaction.classification) not in {"rejection_confirmed", "rejection_tentative"}:
            return StrategyFamilyDecision(
                available=False,
                family="none",
                grade="F",
                score=0.0,
                reason="range_rotation_no_reversal_signal",
                entry_model=None,
            )

        dist_atr = abs(context.last_price - zone.mid) / max(context.atr15, 1e-9)
        reaction_input = dict(reaction.input or {})
        session_quality_raw = float(reaction_input.get("session_quality", 0.0))

        range_definition_score = clamp((1.0 - context.regime_15m) * 20.0 + (4.0 if abs(context.v) <= 0.35 else 0.0), 0.0, 20.0)
        if dist_atr <= 0.35:
            edge_proximity_score = 20.0
        elif dist_atr <= 0.55:
            edge_proximity_score = 16.0
        elif dist_atr <= self.settings.range_rotation_max_center_distance_atr:
            edge_proximity_score = 10.0
        else:
            edge_proximity_score = 0.0

        liquidity_grab_score = clamp(reaction.rejection_score / 4.5, 0.0, 20.0)
        reversal_quality_score = clamp((reaction.rejection_score - reaction.acceptance_score) / 3.0, 0.0, 15.0)

        if self.settings.range_rotation_min_width_atr <= zone.width_atr <= self.settings.range_rotation_max_width_atr:
            range_width_score = 10.0
        elif zone.width_atr < self.settings.range_rotation_min_width_atr:
            range_width_score = 5.0
        else:
            range_width_score = 3.0

        htf_conflict_score = 10.0 if context.regime_15m <= 0.42 else 6.0 if context.regime_15m <= 0.5 else 2.0
        session_quality_score = clamp(session_quality_raw * 5.0, 0.0, 5.0)

        components = {
            "range_definition": round(range_definition_score, 2),
            "edge_proximity": round(edge_proximity_score, 2),
            "liquidity_grab": round(liquidity_grab_score, 2),
            "reversal_quality": round(reversal_quality_score, 2),
            "range_width": round(range_width_score, 2),
            "htf_conflict": round(htf_conflict_score, 2),
            "session_quality": round(session_quality_score, 2),
        }
        scorecard = self._build_scorecard(
            family="range_rotation",
            grade=self._grade_range_rotation(sum(components.values())),
            raw_components=components,
            buckets={
                "location": range_definition_score + edge_proximity_score,
                "liquidity": liquidity_grab_score,
                "reaction": reversal_quality_score,
                "invalidation": range_width_score + htf_conflict_score,
                "session": session_quality_score,
            },
            trendline_bonus=0.0,
        )
        family_score = round(sum(components.values()), 2)
        grade = self._grade_range_rotation(family_score)
        scorecard["grade"] = grade
        scorecard["score"] = family_score
        scorecard["score_ex_trendline"] = family_score

        if dist_atr > self.settings.range_rotation_max_center_distance_atr:
            return StrategyFamilyDecision(
                available=False,
                family="range_rotation",
                grade=grade,
                score=family_score,
                reason="range_rotation_range_center_block",
                entry_model=None,
                components=components,
                scorecard=scorecard,
            )
        if family_score < self.settings.range_rotation_min_score:
            return StrategyFamilyDecision(
                available=False,
                family="range_rotation",
                grade=grade,
                score=family_score,
                reason="range_rotation_score_below_threshold",
                entry_model=None,
                components=components,
                scorecard=scorecard,
            )
        return StrategyFamilyDecision(
            available=False,
            family="range_rotation",
            grade=grade,
            score=family_score,
            reason="range_rotation_research_only",
            entry_model=None,
            components=components,
            clean_case=False,
            confirm_only=True,
            split={"tp1": 0.5, "tp2": 0.5, "runner": 0.0},
            time_stop_min_bars=3,
            time_stop_max_bars=3,
            scorecard=scorecard,
        )

    def _grade_sweep_reversal(self, score: float) -> str:
        if score >= self.settings.sweep_reversal_grade_a_score:
            return "A"
        if score >= self.settings.sweep_reversal_grade_b_score:
            return "B"
        if score >= self.settings.sweep_reversal_grade_c_score:
            return "C"
        return "F"

    def _grade_trend_continuation(self, score: float) -> str:
        if score >= self.settings.trend_continuation_grade_a_score:
            return "A"
        if score >= self.settings.trend_continuation_grade_b_score:
            return "B"
        if score >= self.settings.trend_continuation_grade_c_score:
            return "C"
        return "F"

    def _grade_range_rotation(self, score: float) -> str:
        if score >= self.settings.range_rotation_grade_a_score:
            return "A"
        if score >= self.settings.range_rotation_grade_b_score:
            return "B"
        if score >= self.settings.range_rotation_grade_c_score:
            return "C"
        return "F"
