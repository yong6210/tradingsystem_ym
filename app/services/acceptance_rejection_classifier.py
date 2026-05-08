from __future__ import annotations

from dataclasses import asdict, dataclass

from app.core.config import Settings, get_settings
from app.db.models import Candle, Zone
from app.services.common import clamp, safe_div
from app.services.context_engine import ContextSnapshot


@dataclass(slots=True)
class ReactionBar:
    o: float
    h: float
    l: float
    c: float


@dataclass(slots=True)
class AcceptanceRejectionInput:
    swept_level: float
    sweep_side: str
    swept_level_type: str
    bars: list[ReactionBar]
    atr5: float
    reclaim_bars: int | None
    displacement_atr: float
    continuation_displacement_atr: float
    follow_through_atr: float
    outside_close_count: int
    dwell_time_bars: int
    inefficiency_created: bool
    retest_hold: bool
    opposite_reclaim_failure: bool
    session_quality: float
    avg_wick_to_body_ratio: float


@dataclass(slots=True)
class AcceptanceRejectionResult:
    available: bool
    classification: str
    rejection_score: float
    acceptance_score: float
    rejection_hard_count: int
    acceptance_hard_count: int
    mixed_reasons: list[str]
    input: dict


class AcceptanceRejectionClassifierService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @staticmethod
    def _wick_to_body_ratio(bar: ReactionBar) -> float:
        body = abs(bar.c - bar.o)
        wick = max(0.0, bar.h - max(bar.o, bar.c)) + max(0.0, min(bar.o, bar.c) - bar.l)
        return safe_div(wick, max(body, 1e-6))

    @staticmethod
    def _bar(candle: Candle) -> ReactionBar:
        return ReactionBar(o=float(candle.o), h=float(candle.h), l=float(candle.l), c=float(candle.c))

    def build_input_with_reason(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        candles_5m: list[Candle] | None,
        sweep_level_override: float | None = None,
        swept_level_type_override: str | None = None,
        min_event_bars: int = 2,
    ) -> tuple[AcceptanceRejectionInput | None, str]:
        if not candles_5m or len(candles_5m) < 3:
            return None, "insufficient_candles"

        level = float(sweep_level_override) if sweep_level_override is not None else (
            float(zone.low) if zone.dir_bias == "support" else float(zone.high)
        )
        sweep_side = "below" if zone.dir_bias == "support" else "above"
        window = candles_5m[-5:]
        sweep_indices = [
            index
            for index, candle in enumerate(window)
            if (candle.l < level if sweep_side == "below" else candle.h > level)
        ]
        if not sweep_indices:
            return None, "no_recent_level_sweep"

        sweep_index = sweep_indices[-1]
        event_candles = window[sweep_index : sweep_index + 3]
        if len(event_candles) < max(int(min_event_bars or 0), 1):
            return None, "insufficient_post_sweep_bars"

        bars = [self._bar(candle) for candle in event_candles]
        outside_close_count = 0
        dwell_time_bars = 0
        reclaim_bars: int | None = None
        for index, bar in enumerate(bars, start=1):
            outside = bar.c < level if sweep_side == "below" else bar.c > level
            if outside:
                outside_close_count += 1
                dwell_time_bars += 1
            if reclaim_bars is None and not outside:
                reclaim_bars = index

        if sweep_side == "below":
            displacement_atr = safe_div(max(bar.h for bar in bars) - level, context.atr5)
            continuation_displacement_atr = safe_div(level - min(bar.l for bar in bars), context.atr5)
            follow_through_atr = safe_div(bars[-1].c - level, context.atr5)
            inefficiency_created = len(bars) >= 3 and bars[0].h < bars[2].l
        else:
            displacement_atr = safe_div(level - min(bar.l for bar in bars), context.atr5)
            continuation_displacement_atr = safe_div(max(bar.h for bar in bars) - level, context.atr5)
            follow_through_atr = safe_div(level - bars[-1].c, context.atr5)
            inefficiency_created = len(bars) >= 3 and bars[0].l > bars[2].h

        retest_band = max(context.atr5 * 0.25, 1e-6)
        if sweep_side == "below":
            if reclaim_bars is not None:
                future = bars[reclaim_bars:]
                retest_hold = bool(
                    future
                    and any(bar.l <= level + retest_band for bar in future)
                    and all(bar.c >= level for bar in future)
                )
            else:
                retest_hold = bool(
                    outside_close_count >= self.settings.reaction_classifier_acceptance_min_outside_closes
                    and any(bar.h >= level - retest_band for bar in bars[1:])
                    and bars[-1].c < level
                )
        else:
            if reclaim_bars is not None:
                future = bars[reclaim_bars:]
                retest_hold = bool(
                    future
                    and any(bar.h >= level - retest_band for bar in future)
                    and all(bar.c <= level for bar in future)
                )
            else:
                retest_hold = bool(
                    outside_close_count >= self.settings.reaction_classifier_acceptance_min_outside_closes
                    and any(bar.l <= level + retest_band for bar in bars[1:])
                    and bars[-1].c > level
                )

        session_quality = clamp(1.0 - (0.65 * context.friction_5m + 0.35 * context.jump_rate_5m), 0.0, 1.0)
        avg_wick_to_body_ratio = sum(self._wick_to_body_ratio(bar) for bar in bars) / len(bars)

        return AcceptanceRejectionInput(
            swept_level=level,
            sweep_side=sweep_side,
            swept_level_type=str(swept_level_type_override or zone.type),
            bars=bars,
            atr5=float(context.atr5),
            reclaim_bars=reclaim_bars,
            displacement_atr=float(displacement_atr),
            continuation_displacement_atr=float(continuation_displacement_atr),
            follow_through_atr=float(follow_through_atr),
            outside_close_count=int(outside_close_count),
            dwell_time_bars=int(dwell_time_bars),
            inefficiency_created=bool(inefficiency_created),
            retest_hold=bool(retest_hold),
            opposite_reclaim_failure=bool(reclaim_bars is None or reclaim_bars > self.settings.reaction_classifier_max_reclaim_bars),
            session_quality=float(session_quality),
            avg_wick_to_body_ratio=float(avg_wick_to_body_ratio),
        ), "ok"

    def build_input(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        candles_5m: list[Candle] | None,
        min_event_bars: int = 2,
    ) -> AcceptanceRejectionInput | None:
        payload, _ = self.build_input_with_reason(
            zone=zone,
            context=context,
            candles_5m=candles_5m,
            min_event_bars=min_event_bars,
        )
        return payload

    def classify(self, data: AcceptanceRejectionInput | None) -> AcceptanceRejectionResult:
        if data is None:
            return AcceptanceRejectionResult(
                available=False,
                classification="not_applicable",
                rejection_score=0.0,
                acceptance_score=0.0,
                rejection_hard_count=0,
                acceptance_hard_count=0,
                mixed_reasons=[],
                input={},
            )

        reclaim_speed = (
            20.0
            if data.reclaim_bars == 1
            else 16.0
            if data.reclaim_bars == 2
            else 12.0
            if data.reclaim_bars == 3
            else 0.0
        )
        displacement_strength = (
            20.0
            if data.displacement_atr >= 1.6
            else 16.0
            if data.displacement_atr >= self.settings.reaction_classifier_rejection_displacement_atr
            else 10.0
            if data.displacement_atr >= 0.9
            else 6.0
            if data.displacement_atr >= 0.6
            else 0.0
        )
        close_quality = (
            15.0
            if data.outside_close_count == 0
            else 12.0
            if data.outside_close_count == 1
            else 6.0
            if data.outside_close_count == 2
            else 0.0
        )
        follow_through = (
            15.0
            if data.follow_through_atr >= 1.0
            else 10.0
            if data.follow_through_atr >= 0.6
            else 5.0
            if data.follow_through_atr >= 0.3
            else 0.0
        )
        inefficiency = 10.0 if data.inefficiency_created else 0.0
        dwell_penalty_adjusted = 10.0 if data.dwell_time_bars <= 1 else 7.0 if data.dwell_time_bars == 2 else 4.0 if data.dwell_time_bars == 3 else 0.0
        rejection_session = round(data.session_quality * 10.0, 4)
        rejection_score = round(
            reclaim_speed + displacement_strength + close_quality + follow_through + inefficiency + dwell_penalty_adjusted + rejection_session,
            4,
        )

        close_beyond = 20.0 if data.outside_close_count >= 3 else 16.0 if data.outside_close_count >= 2 else 8.0 if data.outside_close_count == 1 else 0.0
        hold_beyond = 20.0 if data.dwell_time_bars >= 3 else 14.0 if data.dwell_time_bars >= 2 else 6.0 if data.dwell_time_bars == 1 else 0.0
        retest_success = 15.0 if data.retest_hold else 0.0
        continuation_strength = (
            15.0
            if data.continuation_displacement_atr >= 1.2
            else 10.0
            if data.continuation_displacement_atr >= 0.8
            else 5.0
            if data.continuation_displacement_atr >= 0.5
            else 0.0
        )
        opposite_reclaim_failure = 15.0 if data.opposite_reclaim_failure else 0.0
        acceptance_dwell = 10.0 if data.dwell_time_bars >= 3 else 7.0 if data.dwell_time_bars >= 2 else 4.0 if data.dwell_time_bars == 1 else 0.0
        acceptance_session = round(data.session_quality * 5.0, 4)
        acceptance_score = round(
            close_beyond + hold_beyond + retest_success + continuation_strength + opposite_reclaim_failure + acceptance_dwell + acceptance_session,
            4,
        )

        rejection_hard_count = int(
            (data.reclaim_bars is not None and 1 <= data.reclaim_bars <= self.settings.reaction_classifier_max_reclaim_bars)
        ) + int(data.displacement_atr >= self.settings.reaction_classifier_rejection_displacement_atr) + int(
            data.outside_close_count <= self.settings.reaction_classifier_rejection_max_outside_closes
        )
        acceptance_hard_count = int(
            data.outside_close_count >= self.settings.reaction_classifier_acceptance_min_outside_closes
        ) + int(data.retest_hold) + int(data.opposite_reclaim_failure)

        rejection_support = int(data.inefficiency_created) + int(data.retest_hold) + int(data.dwell_time_bars <= 1)
        acceptance_support = int(data.continuation_displacement_atr >= 0.8) + int(data.avg_wick_to_body_ratio < 1.8) + int(data.dwell_time_bars >= 2)

        rejection_confirmed = (
            rejection_hard_count == 3
            and rejection_support >= 1
            and rejection_score >= self.settings.reaction_classifier_rejection_confirmed_score
        )
        rejection_tentative = rejection_hard_count >= 2 and rejection_score >= self.settings.reaction_classifier_rejection_tentative_score
        acceptance_confirmed = (
            acceptance_hard_count == 3
            and acceptance_support >= 1
            and acceptance_score >= self.settings.reaction_classifier_acceptance_confirmed_score
        )
        acceptance_tentative = acceptance_hard_count >= 2 and acceptance_score >= self.settings.reaction_classifier_acceptance_tentative_score

        mixed_reasons: list[str] = []
        if data.reclaim_bars is not None and data.follow_through_atr < 0.3:
            mixed_reasons.append("reclaim_without_follow_through")
        if data.avg_wick_to_body_ratio >= 2.0:
            mixed_reasons.append("wick_noise_dominant")
        if rejection_tentative and acceptance_tentative:
            mixed_reasons.append("conflicting_scores")
        if not data.retest_hold and data.reclaim_bars is not None and data.dwell_time_bars >= 2:
            mixed_reasons.append("failed_retest")

        score_gap = rejection_score - acceptance_score
        if rejection_confirmed and not acceptance_confirmed and score_gap >= 5.0:
            classification = "rejection_confirmed"
        elif acceptance_confirmed and not rejection_confirmed and score_gap <= -5.0:
            classification = "acceptance_confirmed"
        elif rejection_tentative and not acceptance_tentative and score_gap > 5.0:
            classification = "rejection_tentative"
        elif acceptance_tentative and not rejection_tentative and score_gap < -5.0:
            classification = "acceptance_tentative"
        else:
            classification = "mixed"
            if not mixed_reasons:
                mixed_reasons.append("score_below_threshold")

        input_summary = asdict(data)
        input_summary["bars"] = [asdict(bar) for bar in data.bars]
        return AcceptanceRejectionResult(
            available=True,
            classification=classification,
            rejection_score=float(rejection_score),
            acceptance_score=float(acceptance_score),
            rejection_hard_count=int(rejection_hard_count),
            acceptance_hard_count=int(acceptance_hard_count),
            mixed_reasons=mixed_reasons,
            input=input_summary,
        )

    def classify_zone(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        candles_5m: list[Candle] | None,
    ) -> AcceptanceRejectionResult:
        return self.classify(self.build_input(zone=zone, context=context, candles_5m=candles_5m))
