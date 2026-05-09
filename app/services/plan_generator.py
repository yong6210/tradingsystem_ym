from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from app.core.config import get_settings
from app.core.enums import Direction, EntryModel, PlanState
from app.db.models import Candle, Plan, Zone
from app.services.acceptance_rejection_classifier import AcceptanceRejectionClassifierService
from app.services.acceptance_rejection_classifier import AcceptanceRejectionResult
from app.services.common import clamp
from app.services.context_engine import ContextSnapshot
from app.services.execution_router import EntryDecision, EntryModelRouter
from app.services.position_sizing import PositionSizingInput, PositionSizingService
from app.services.session_guidance import SessionGuidanceService
from app.services.strategy_family_router import StrategyFamilyDecision, StrategyFamilyRouter
from app.services.strategy_mode import StrategyModeService
from app.services.thesis_fingerprint import ThesisFingerprintService


@dataclass
class RankedPlan:
    plan: Plan
    final_rank_score: float
    friction_penalty: float


@dataclass(slots=True)
class RegimeProfile:
    name: str
    min_confluence: float
    rr_floor: float
    ev_floor: float
    weight_liquidity: float
    weight_fvg_displacement: float
    weight_htf_alignment: float
    weight_ob_freshness: float
    weight_trend_proxy: float


class PlanGenerator:
    _REACTION_SHADOW_ZONE_BAND_FRACTION = 0.25
    _REACTION_SHADOW_ONE_BAR_MIN_EVENT_BARS = 1
    _PROOF_RECLAIM_LOOKBACK_TOTAL_BARS = 30
    _PROOF_RECLAIM_EXCLUDE_RECENT_BARS = 6
    _PROOF_RECLAIM_SWEEP_ATR_THRESHOLD = 0.08

    def __init__(self):
        self.settings = get_settings()
        self.router = EntryModelRouter()
        self.reaction_classifier = AcceptanceRejectionClassifierService(self.settings)
        self.strategy_family_router = StrategyFamilyRouter(self.settings)
        self.strategy_mode = StrategyModeService(self.settings)
        self.thesis = ThesisFingerprintService()
        self.sizing = PositionSizingService(self.settings)
        self.session_guidance = SessionGuidanceService(self.settings)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if isfinite(parsed) else default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return int(parsed) if isfinite(parsed) else default

    def _fast_failure_validity(
        self,
        *,
        symbol: str,
        strategy_family: str,
        entry_model: EntryModel,
        session_name: str,
    ) -> dict[str, Any]:
        if str(symbol or "").strip().upper() != "BTCUSDC":
            return {}
        if str(strategy_family or "").strip().lower() != "sweep_reversal":
            return {}
        if str(entry_model.value if isinstance(entry_model, EntryModel) else entry_model).strip().upper() != EntryModel.LIMIT.value:
            return {}
        if not bool(self.settings.btc_sweep_reversal_limit_fast_failure_enabled):
            return {}
        allowed_sessions = {
            item.strip().lower()
            for item in str(self.settings.btc_sweep_reversal_limit_fast_failure_allowed_sessions or "").split(",")
            if item.strip()
        }
        normalized_session_name = str(session_name or "").strip().lower()
        if allowed_sessions and normalized_session_name not in allowed_sessions:
            return {}
        max_bars = max(self._safe_int(self.settings.btc_sweep_reversal_limit_fast_failure_max_bars, default=18), 0)
        stop_r = self._safe_float(self.settings.btc_sweep_reversal_limit_fast_failure_stop_r, default=0.00000001)
        requires_sl_touch = bool(self.settings.btc_sweep_reversal_limit_fast_failure_requires_sl_touch)
        if max_bars <= 0 or stop_r <= 0.0 or stop_r >= 1.0:
            return {}
        return {
            "strategy_fast_failure_enabled": True,
            "strategy_fast_failure_policy": "btc_sweep_reversal_limit_initial_guard_stop",
            "strategy_fast_failure_session_name": normalized_session_name,
            "strategy_fast_failure_max_bars": max_bars,
            "strategy_fast_failure_stop_r": round(stop_r, 8),
            "strategy_fast_failure_requires_sl_touch": requires_sl_touch,
        }

    def resolve_regime_label(self, context: ContextSnapshot) -> str:
        return self._resolve_regime_label(context)

    def _resolve_regime_label(self, context: ContextSnapshot) -> str:
        if context.regime_label in {"trend", "range", "shock", "transition"}:
            return context.regime_label
        if context.transition_state == "transition_confirmed":
            return "transition"
        if context.jump_rate_5m >= self.settings.jump_hard_gate * 0.9 or context.friction_5m >= self.settings.friction_hard_gate * 0.9:
            return "shock"
        if context.regime_15m >= 0.64:
            return "trend"
        return "range"

    @staticmethod
    def _direction(zone: Zone) -> Direction:
        return Direction.LONG if zone.dir_bias == "support" else Direction.SHORT

    @staticmethod
    def _zone_strength(zone: Zone, context: ContextSnapshot) -> float:
        touch_penalty = max(0.0, (zone.touch_count - 3) * 3.5)
        width_penalty = max(0.0, (zone.width_atr - 0.8) * 20.0)
        friction_penalty = context.friction_5m * 12.0
        return clamp(zone.base_strength + zone.quality * 0.3 - touch_penalty - width_penalty - friction_penalty, 0.0, 100.0)

    @staticmethod
    def _approach_score(zone: Zone, context: ContextSnapshot) -> float:
        dist_atr = abs(context.last_price - zone.mid) / max(context.atr15, 1e-9)
        dist_score = clamp(100.0 - dist_atr * 20.0, 0.0, 100.0)

        if zone.dir_bias == "support":
            align = 1.0 if context.v >= 0 else 0.4
        else:
            align = 1.0 if context.v <= 0 else 0.4

        rejection_bonus = clamp(-context.sevt * 15.0, -10.0, 15.0)
        friction_penalty = context.friction_5m * 20.0

        raw = dist_score * 0.6 + align * 30.0 + rejection_bonus - friction_penalty
        return clamp(raw, 0.0, 100.0)

    @staticmethod
    def _find_near_lp(zone: Zone, zones: list[Zone], atr15: float) -> bool:
        for other in zones:
            if other.zone_id == zone.zone_id:
                continue
            if other.type != "LP":
                continue
            if abs(other.mid - zone.mid) <= 0.6 * atr15:
                return True
        return False

    def _regime_profile(self, context: ContextSnapshot) -> RegimeProfile:
        label = self._resolve_regime_label(context)

        if label == "trend":
            return RegimeProfile(
                name="trend",
                min_confluence=self.settings.min_confluence_score + 4.0,
                rr_floor=max(self.settings.min_rr, 1.30),
                ev_floor=0.00,
                weight_liquidity=0.28,
                weight_fvg_displacement=0.20,
                weight_htf_alignment=0.30,
                weight_ob_freshness=0.17,
                weight_trend_proxy=0.05,
            )

        if label == "shock":
            return RegimeProfile(
                name="shock",
                min_confluence=self.settings.min_confluence_score + 10.0,
                rr_floor=max(self.settings.min_rr, 1.45),
                ev_floor=0.05,
                weight_liquidity=0.42,
                weight_fvg_displacement=0.30,
                weight_htf_alignment=0.13,
                weight_ob_freshness=0.10,
                weight_trend_proxy=0.05,
            )

        if label == "transition":
            return RegimeProfile(
                name="transition",
                min_confluence=self.settings.min_confluence_score + 14.0,
                rr_floor=max(self.settings.min_rr, 1.60),
                ev_floor=0.08,
                weight_liquidity=0.44,
                weight_fvg_displacement=0.24,
                weight_htf_alignment=0.14,
                weight_ob_freshness=0.13,
                weight_trend_proxy=0.05,
            )

        return RegimeProfile(
            name="range",
            min_confluence=self.settings.min_confluence_score,
            rr_floor=self.settings.min_rr,
            ev_floor=0.00,
            weight_liquidity=0.38,
            weight_fvg_displacement=0.20,
            weight_htf_alignment=0.18,
            weight_ob_freshness=0.19,
            weight_trend_proxy=0.05,
        )

    def feature_weights_for_regime(self, regime_label: str) -> dict[str, float]:
        if regime_label == "trend":
            profile = RegimeProfile(
                name="trend",
                min_confluence=self.settings.min_confluence_score + 4.0,
                rr_floor=max(self.settings.min_rr, 1.30),
                ev_floor=0.00,
                weight_liquidity=0.28,
                weight_fvg_displacement=0.20,
                weight_htf_alignment=0.30,
                weight_ob_freshness=0.17,
                weight_trend_proxy=0.05,
            )
        elif regime_label == "shock":
            profile = RegimeProfile(
                name="shock",
                min_confluence=self.settings.min_confluence_score + 10.0,
                rr_floor=max(self.settings.min_rr, 1.45),
                ev_floor=0.05,
                weight_liquidity=0.42,
                weight_fvg_displacement=0.30,
                weight_htf_alignment=0.13,
                weight_ob_freshness=0.10,
                weight_trend_proxy=0.05,
            )
        elif regime_label == "transition":
            profile = RegimeProfile(
                name="transition",
                min_confluence=self.settings.min_confluence_score + 14.0,
                rr_floor=max(self.settings.min_rr, 1.60),
                ev_floor=0.08,
                weight_liquidity=0.44,
                weight_fvg_displacement=0.24,
                weight_htf_alignment=0.14,
                weight_ob_freshness=0.13,
                weight_trend_proxy=0.05,
            )
        else:
            profile = RegimeProfile(
                name="range",
                min_confluence=self.settings.min_confluence_score,
                rr_floor=self.settings.min_rr,
                ev_floor=0.00,
                weight_liquidity=0.38,
                weight_fvg_displacement=0.20,
                weight_htf_alignment=0.18,
                weight_ob_freshness=0.19,
                weight_trend_proxy=0.05,
            )
        return {
            "liquidity": profile.weight_liquidity,
            "fvg_displacement": profile.weight_fvg_displacement,
            "htf_alignment": profile.weight_htf_alignment,
            "ob_freshness": profile.weight_ob_freshness,
            "trend_proxy": profile.weight_trend_proxy,
        }

    @staticmethod
    def _normalize_weights(weights: dict[str, float], *, min_weight: float) -> dict[str, float]:
        bounded = {key: max(min_weight, float(value)) for key, value in weights.items()}
        total = sum(bounded.values())
        if total <= 1e-9:
            fallback = 1.0 / max(len(bounded), 1)
            return {key: fallback for key in bounded}
        return {key: value / total for key, value in bounded.items()}

    def _active_feature_weights(
        self,
        *,
        profile: RegimeProfile,
        feature_overrides: dict[str, float] | None = None,
        importance_calibration: dict[str, dict] | None = None,
    ) -> tuple[dict[str, float], dict[str, float]]:
        base_weights = self.feature_weights_for_regime(profile.name)
        active_weights = dict(base_weights)
        if (
            importance_calibration
            and self.settings.feature_calibration_enabled
            and self.settings.feature_calibration_apply_runtime
            and bool(importance_calibration.get("available"))
        ):
            regime_row = dict((importance_calibration.get("by_regime") or {}).get(profile.name, {}))
            calibrated = regime_row.get("feature_weights_active")
            if isinstance(calibrated, dict):
                for key, value in calibrated.items():
                    if key in active_weights:
                        active_weights[key] = self._safe_float(value, default=active_weights[key])

        if feature_overrides:
            for key, value in feature_overrides.items():
                if key in active_weights:
                    active_weights[key] = max(0.0, self._safe_float(value))

        active_weights = self._normalize_weights(
            active_weights,
            min_weight=max(0.0, self._safe_float(self.settings.feature_calibration_min_weight, default=0.05)),
        )
        return base_weights, active_weights

    def _zone_type_calibration_multiplier(
        self,
        *,
        zone_type: str,
        importance_calibration: dict[str, dict] | None = None,
    ) -> float:
        if not importance_calibration or not bool(importance_calibration.get("available")):
            return 1.0
        row = dict((importance_calibration.get("zone_type_multipliers") or {}).get(zone_type, {}))
        multiplier = row.get("active_multiplier")
        if multiplier is None:
            return 1.0
        return clamp(float(multiplier), 0.75, 1.25)

    def _zone_type_multiplier(
        self,
        zone_type: str,
        stats: dict,
        profile: RegimeProfile,
        importance_calibration: dict[str, dict] | None = None,
    ) -> float:
        base = {
            "OB": self.settings.weight_zone_ob,
            "FVG": self.settings.weight_zone_fvg,
            "LP": self.settings.weight_zone_lp,
            "FLIP": self.settings.weight_zone_flip,
        }.get(zone_type, 0.75)

        sample = float(stats.get("sample_size", 0.0))
        sample_factor = clamp(sample / max(self.settings.min_zone_sample_for_full_confidence, 1), 0.0, 1.0)
        ev_r = float(stats.get("ev_r", 0.0))
        edge_multiplier = clamp(0.92 + ev_r * 0.10, 0.70, 1.25)

        regime_multiplier = 1.0
        if profile.name == "trend":
            if zone_type == "OB":
                regime_multiplier = 1.05
            elif zone_type == "FLIP":
                regime_multiplier = 0.92
        elif profile.name == "range":
            if zone_type in {"LP", "OB"}:
                regime_multiplier = 1.04
            elif zone_type == "FVG":
                regime_multiplier = 0.95
        elif profile.name == "transition":
            if zone_type == "LP":
                regime_multiplier = 0.92
            elif zone_type == "FLIP":
                regime_multiplier = 0.80
        else:  # shock
            if zone_type == "LP":
                regime_multiplier = 1.06
            elif zone_type == "FLIP":
                regime_multiplier = 0.85

        learned_multiplier = (1.0 - sample_factor) + sample_factor * edge_multiplier
        calibration_multiplier = self._zone_type_calibration_multiplier(
            zone_type=zone_type,
            importance_calibration=importance_calibration,
        )
        return clamp(base * regime_multiplier * learned_multiplier * calibration_multiplier, 0.55, 1.35)

    @staticmethod
    def _trend_alignment_score(zone: Zone, context: ContextSnapshot) -> float:
        trend = 0.5 * context.v + 0.5 * context.sdir
        if zone.dir_bias == "support":
            raw = 50.0 + trend * 50.0
        else:
            raw = 50.0 - trend * 50.0
        return clamp(raw, 0.0, 100.0)

    @staticmethod
    def _zone_created_at(zone: Zone) -> datetime:
        created = zone.created_ts
        if created.tzinfo is None:
            return created.replace(tzinfo=timezone.utc)
        return created.astimezone(timezone.utc)

    def _zone_age_hours(self, zone: Zone, *, now: datetime) -> float:
        age = now - self._zone_created_at(zone)
        return max(0.0, age.total_seconds() / 3600.0)

    @staticmethod
    def _compact_alias(payload: dict[str, Any]) -> dict[str, Any] | None:
        compact: dict[str, Any] = {}
        for key, value in payload.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            compact[key] = value
        return compact or None

    @staticmethod
    def _location_primary_type(liquidity_narrative: str, zone_type: str) -> str:
        narrative = str(liquidity_narrative or "").lower()
        mapping = {
            "session_high_sweep": "session_high_liquidity",
            "session_low_sweep": "session_low_liquidity",
            "trend_pullback_to_discount": "discount_pullback",
            "trend_pullback_to_premium": "premium_pullback",
            "range_upper_reject": "range_upper_edge",
            "range_lower_reject": "range_lower_edge",
        }
        if narrative in mapping:
            return mapping[narrative]
        zone_type_normalized = str(zone_type or "").upper()
        if zone_type_normalized == "LP":
            return "liquidity_pool"
        if zone_type_normalized == "FLIP":
            return "flip_level"
        if zone_type_normalized == "OB":
            return "order_block_context"
        if zone_type_normalized == "FVG":
            return "inefficiency_context"
        return "location_context"

    def _build_location_reference(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        entry_price: float,
        thesis_fingerprint: dict[str, Any] | None,
        near_lp: bool,
    ) -> dict[str, Any] | None:
        liquidity_narrative = str((thesis_fingerprint or {}).get("liquidity_narrative") or "")
        primary_type = self._location_primary_type(liquidity_narrative, zone.type)
        secondary_type = "nearby_liquidity_pool" if near_lp and zone.type != "LP" else str(zone.type or "").lower()
        edge_proximity_atr = min(abs(float(entry_price) - float(zone.low)), abs(float(entry_price) - float(zone.high))) / max(
            float(context.atr15),
            1e-9,
        )
        session_box_role = (
            "reference_only"
            if primary_type in {"session_high_liquidity", "session_low_liquidity", "liquidity_pool"}
            else "refinement_only"
        )
        return self._compact_alias(
            {
                "primary_type": primary_type,
                "primary_label": liquidity_narrative or primary_type,
                "secondary_type": secondary_type,
                "session_box_role": session_box_role,
                "edge_proximity_atr": round(float(edge_proximity_atr), 4),
            }
        )

    @staticmethod
    def _session_reference_type(liquidity_narrative: str, zone_type: str, near_lp: bool) -> str | None:
        narrative = str(liquidity_narrative or "").lower()
        if narrative in {"session_high_sweep", "range_upper_reject"}:
            return "session_high_reference"
        if narrative in {"session_low_sweep", "range_lower_reject"}:
            return "session_low_reference"
        if str(zone_type or "").upper() == "LP" or near_lp:
            return "liquidity_pool_reference"
        return None

    def _build_session_liquidity_reference(
        self,
        *,
        zone: Zone,
        reaction_classification: str,
        reaction_input: dict[str, Any] | None,
        thesis_fingerprint: dict[str, Any] | None,
        near_lp: bool,
        now: datetime,
    ) -> dict[str, Any] | None:
        liquidity_narrative = str((thesis_fingerprint or {}).get("liquidity_narrative") or "")
        reference_type = self._session_reference_type(liquidity_narrative, zone.type, near_lp)
        if reference_type is None:
            return None

        payload = dict(reaction_input or {})
        outside_close_count = int(payload.get("outside_close_count", 0) or 0)
        if outside_close_count <= 0:
            outside_close_state = "no_outside_close"
        elif outside_close_count == 1:
            outside_close_state = "single_outside_close"
        else:
            outside_close_state = "multi_outside_close"
        failed_acceptance = str(reaction_classification or "").lower().startswith("rejection_") and outside_close_count > 0

        return self._compact_alias(
            {
                "reference_type": reference_type,
                "range_high": round(float(zone.high), 4),
                "range_low": round(float(zone.low), 4),
                "breakout_side": str(payload.get("sweep_side") or "").lower() or None,
                "outside_close_state": outside_close_state,
                "failed_acceptance": bool(failed_acceptance),
                "as_of_ts": now.astimezone(timezone.utc).isoformat(),
            }
        )

    @staticmethod
    def _reaction_structure_shift_hint(reaction_classification: str) -> str:
        classification = str(reaction_classification or "").lower()
        if classification in {"rejection_confirmed", "rejection_tentative"}:
            return "rejection_bias"
        if classification in {"acceptance_confirmed", "acceptance_tentative"}:
            return "acceptance_bias"
        if classification == "mixed":
            return "mixed_response"
        return "not_available"

    @staticmethod
    def _reaction_reclaim_speed_bucket(reclaim_bars: Any) -> str:
        if reclaim_bars == 1:
            return "fast"
        if reclaim_bars == 2:
            return "moderate"
        if reclaim_bars in {3, None}:
            return "slow_or_absent"
        return "not_available"

    @staticmethod
    def _reaction_close_outside_bucket(outside_close_count: Any) -> str:
        if outside_close_count is None:
            return "not_available"
        count = int(outside_close_count or 0)
        if count <= 0:
            return "none"
        if count == 1:
            return "single"
        return "multiple"

    @staticmethod
    def _reaction_retest_status(
        *,
        retest_hold: Any,
        reclaim_bars: Any,
        outside_close_count: Any,
        dwell_time_bars: Any,
    ) -> str:
        if retest_hold is True:
            return "held"
        if retest_hold is None:
            return "not_available"
        outside_count = int(outside_close_count or 0) if outside_close_count is not None else None
        dwell_bars = int(dwell_time_bars or 0) if dwell_time_bars is not None else None
        if reclaim_bars is not None or (outside_count is not None and outside_count >= 2) or (dwell_bars is not None and dwell_bars >= 2):
            return "failed"
        return "not_observed"

    @staticmethod
    def _reaction_efficiency_state(inefficiency_created: Any) -> str:
        if inefficiency_created is True:
            return "inefficiency_created"
        if inefficiency_created is False:
            return "no_inefficiency"
        return "not_available"

    def _build_reaction_evidence(
        self,
        *,
        reaction_classification: str,
        reaction_input: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = dict(reaction_input or {})
        if not payload and str(reaction_classification or "").lower() in {"", "not_applicable"}:
            return None

        reaction_evidence = {
            "structure_shift_hint": self._reaction_structure_shift_hint(reaction_classification),
            "reclaim_speed_bucket": self._reaction_reclaim_speed_bucket(payload.get("reclaim_bars")),
            "close_outside_bucket": self._reaction_close_outside_bucket(payload.get("outside_close_count")),
            "retest_status": self._reaction_retest_status(
                retest_hold=payload.get("retest_hold"),
                reclaim_bars=payload.get("reclaim_bars"),
                outside_close_count=payload.get("outside_close_count"),
                dwell_time_bars=payload.get("dwell_time_bars"),
            ),
            "efficiency_state": self._reaction_efficiency_state(payload.get("inefficiency_created")),
        }
        actionable = any(value not in {None, "not_available"} for value in reaction_evidence.values())
        if not actionable:
            return None
        return self._compact_alias(reaction_evidence)

    def _build_runtime_signal_telemetry(
        self,
        *,
        context: ContextSnapshot,
        zone: Zone,
        direction: Direction,
        strategy_family: str,
        entry_price: float,
        sl: float,
        location_reference: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        base = dict(getattr(context, "signal_telemetry", {}) or {})
        if not base:
            return None

        latest_close = float(context.last_price)
        entry_price = float(entry_price)
        sl = float(sl)
        risk_abs = max(abs(entry_price - sl), 1e-9)
        atr_abs = max(float(context.atr15), 1e-9)
        close_position = float(base.get("close_position", 0.5) or 0.5)
        close_vs_ema_fast_atr = float(base.get("close_vs_ema_fast_atr", 0.0) or 0.0)

        if direction == Direction.SHORT:
            directional_close_position = 1.0 - close_position
            sweep_distance_atr = float(base.get("short_sweep_distance_atr", 0.0) or 0.0)
            reclaim_distance_atr = float(base.get("short_reclaim_distance_atr", 0.0) or 0.0)
            directional_close_vs_ema_fast_atr = -close_vs_ema_fast_atr
            entry_offset_abs = max(entry_price - latest_close, 0.0)
        else:
            directional_close_position = close_position
            sweep_distance_atr = float(base.get("long_sweep_distance_atr", 0.0) or 0.0)
            reclaim_distance_atr = float(base.get("long_reclaim_distance_atr", 0.0) or 0.0)
            directional_close_vs_ema_fast_atr = close_vs_ema_fast_atr
            entry_offset_abs = max(latest_close - entry_price, 0.0)

        telemetry = {
            "telemetry_source": str(base.get("telemetry_source") or "context_snapshot"),
            "telemetry_version": str(base.get("telemetry_version") or "v1"),
            "signal_family": str(strategy_family or "").strip().lower() or None,
            "direction": direction.value,
            "zone_type": str(zone.type or "").upper() or None,
            "zone_width_atr": round(float(zone.width_atr), 4),
            "prior_window_bars": int(base.get("prior_window_bars", 0) or 0),
            "close_position": round(close_position, 4),
            "directional_close_position": round(directional_close_position, 4),
            "body_fraction": round(float(base.get("body_fraction", 0.0) or 0.0), 4),
            "range_atr": round(float(base.get("range_atr", 0.0) or 0.0), 4),
            "body_atr": round(float(base.get("body_atr", 0.0) or 0.0), 4),
            "prior_range_atr": round(float(base.get("prior_range_atr", 0.0) or 0.0), 4),
            "sweep_distance_atr": round(sweep_distance_atr, 4),
            "reclaim_distance_atr": round(reclaim_distance_atr, 4),
            "ema_spread_atr": round(float(base.get("ema_spread_atr", 0.0) or 0.0), 4),
            "directional_close_vs_ema_fast_atr": round(directional_close_vs_ema_fast_atr, 4),
            "entry_offset_atr": round(float(entry_offset_abs / atr_abs), 4),
            "entry_offset_r": round(float(entry_offset_abs / risk_abs), 4),
            "risk_atr": round(float(risk_abs / atr_abs), 4),
            "edge_proximity_atr": location_reference.get("edge_proximity_atr") if location_reference else None,
        }
        return self._compact_alias(telemetry)

    def _build_runtime_signal_shadow_tilt(
        self,
        *,
        symbol: str,
        strategy_family: str,
        entry_model: EntryModel,
        direction: Direction,
        runtime_signal_telemetry: dict[str, Any] | None,
        base_recommended_risk_r: float,
        expected_ev_r: float,
    ) -> dict[str, Any] | None:
        if not bool(self.settings.btc_sweep_reversal_limit_runtime_signal_shadow_tilt_enabled):
            return None
        if str(symbol or "").strip().upper() != "BTCUSDC":
            return None
        if str(strategy_family or "").strip().lower() != "sweep_reversal":
            return None
        if entry_model != EntryModel.LIMIT:
            return None
        telemetry = dict(runtime_signal_telemetry or {})
        if not telemetry:
            return None

        policy = "btc_sweep_reversal_limit_runtime_signal_shadow_tilt_v1"
        multiplier = 1.0
        classification = "neutral"
        reason_code = "shadow_hold_neutral"
        reason = "No honest-runtime tilt matched; keep baseline size in live and only log the shadow view."

        if direction == Direction.LONG:
            weaken_threshold = self._safe_float(
                self.settings.btc_sweep_reversal_limit_runtime_signal_shadow_tilt_long_weaken_close_vs_ema_fast_atr,
                default=-0.6978,
            )
            observed = float(telemetry.get("directional_close_vs_ema_fast_atr", 0.0) or 0.0)
            if observed >= weaken_threshold:
                multiplier = self._safe_float(
                    self.settings.btc_sweep_reversal_limit_runtime_signal_shadow_tilt_long_size_factor,
                    default=0.75,
                )
                classification = "weak_long_understretch"
                reason_code = "shadow_reduce_weak_long"
                reason = "Honest BTC subset showed weaker long EV when close-vs-EMA stretch was not deep enough."
        elif direction == Direction.SHORT:
            strength_threshold = self._safe_float(
                self.settings.btc_sweep_reversal_limit_runtime_signal_shadow_tilt_short_strength_sweep_distance_atr,
                default=0.4107,
            )
            observed = float(telemetry.get("sweep_distance_atr", 0.0) or 0.0)
            if observed >= strength_threshold:
                multiplier = self._safe_float(
                    self.settings.btc_sweep_reversal_limit_runtime_signal_shadow_tilt_short_size_factor,
                    default=1.4762,
                )
                classification = "strong_short_sweep"
                reason_code = "shadow_increase_strong_short"
                reason = "Honest BTC subset showed stronger short EV when sweep distance expanded into the upper bucket."

        shadow_recommended_risk_r = round(float(base_recommended_risk_r) * multiplier, 4)
        shadow_expected_ev_at_size_r = round(float(expected_ev_r) * shadow_recommended_risk_r, 4)
        base_expected_ev_at_size_r = round(float(expected_ev_r) * float(base_recommended_risk_r), 4)
        payload = {
            "policy": policy,
            "apply_live": False,
            "classification": classification,
            "reason_code": reason_code,
            "reason": reason,
            "base_recommended_risk_r": round(float(base_recommended_risk_r), 4),
            "shadow_recommended_risk_r": shadow_recommended_risk_r,
            "shadow_size_multiplier": round(float(multiplier), 4),
            "base_expected_ev_at_size_r": base_expected_ev_at_size_r,
            "shadow_expected_ev_at_size_r": shadow_expected_ev_at_size_r,
            "delta_expected_ev_at_size_r": round(shadow_expected_ev_at_size_r - base_expected_ev_at_size_r, 4),
            "long_weaken_close_vs_ema_fast_atr_threshold": round(
                self._safe_float(
                    self.settings.btc_sweep_reversal_limit_runtime_signal_shadow_tilt_long_weaken_close_vs_ema_fast_atr,
                    default=-0.6978,
                ),
                4,
            ),
            "short_strength_sweep_distance_atr_threshold": round(
                self._safe_float(
                    self.settings.btc_sweep_reversal_limit_runtime_signal_shadow_tilt_short_strength_sweep_distance_atr,
                    default=0.4107,
                ),
                4,
            ),
        }
        return self._compact_alias(payload)

    def _zone_is_stale_for_scalp(self, zone: Zone, *, now: datetime) -> bool:
        return self._zone_age_hours(zone, now=now) > self._safe_float(self.settings.scalp_zone_hard_max_age_hours, default=24.0)

    def _ob_freshness_score(self, zone: Zone, *, now: datetime) -> float:
        freshness = 100.0 - max(0, zone.touch_count - 1) * 14.0 - max(0.0, zone.width_atr - 0.8) * 22.0
        if zone.type == "OB":
            freshness += 8.0
        age_hours = self._zone_age_hours(zone, now=now)
        recent_boost_hours = self._safe_float(self.settings.scalp_zone_recent_boost_hours, default=6.0)
        if age_hours <= recent_boost_hours:
            freshness += 10.0
        else:
            freshness -= (age_hours - recent_boost_hours) * self._safe_float(
                self.settings.scalp_zone_age_penalty_per_hour,
                default=1.6,
            )
        return clamp(freshness, 0.0, 100.0)

    @staticmethod
    def _liquidity_score(zone: Zone, context: ContextSnapshot, near_lp: bool) -> float:
        if zone.type == "LP":
            base = 82.0
        elif near_lp:
            base = 75.0
        else:
            base = 62.0

        if zone.dir_bias == "support" and context.sevt < 0:
            base += 8.0
        if zone.dir_bias == "resistance" and context.sevt > 0:
            base += 8.0

        penalty = context.jump_rate_5m * 45.0 + context.friction_5m * 20.0
        return clamp(base - penalty, 0.0, 100.0)

    @staticmethod
    def _fvg_displacement_score(zone: Zone, context: ContextSnapshot) -> float:
        displacement = 45.0 + clamp((abs(context.v) + abs(context.a)) * 18.0, 0.0, 45.0)
        if zone.type == "FVG":
            displacement += 8.0
        return clamp(displacement, 0.0, 100.0)

    def _is_setup_disabled(self, stats: dict) -> str | None:
        sample_size = float(stats.get("sample_size", 0.0))
        if sample_size < self.settings.auto_disable_min_samples:
            return None

        ev_r = float(stats.get("ev_r", 0.0))
        if ev_r <= self.settings.auto_disable_ev_r_threshold:
            return "setup_negative_ev"

        p1r = float(stats.get("p1r", 0.0))
        p2r = float(stats.get("p2r", 0.0))
        if p1r < 0.44 and p2r < 0.30:
            return "setup_low_hit_rate"

        return None

    def _confluence_score(
        self,
        zone: Zone,
        context: ContextSnapshot,
        near_lp: bool,
        stats: dict,
        profile: RegimeProfile,
        now: datetime,
        feature_overrides: dict[str, float] | None = None,
        importance_calibration: dict[str, dict] | None = None,
    ) -> tuple[float, dict[str, float], dict[str, float], dict[str, float], float]:
        liquidity = self._liquidity_score(zone, context, near_lp)
        fvg_displacement = self._fvg_displacement_score(zone, context)
        htf_alignment = self._trend_alignment_score(zone, context)
        ob_freshness = self._ob_freshness_score(zone, now=now)
        trend_proxy = self._trend_alignment_score(zone, context)

        base_weights, active_weights = self._active_feature_weights(
            profile=profile,
            feature_overrides=feature_overrides,
            importance_calibration=importance_calibration,
        )

        weighted = (
            active_weights["liquidity"] * liquidity
            + active_weights["fvg_displacement"] * fvg_displacement
            + active_weights["htf_alignment"] * htf_alignment
            + active_weights["ob_freshness"] * ob_freshness
            + active_weights["trend_proxy"] * trend_proxy
        )
        zone_type_multiplier = self._zone_type_multiplier(
            zone.type,
            stats,
            profile,
            importance_calibration=importance_calibration,
        )
        score = clamp(weighted * zone_type_multiplier, 0.0, 100.0)
        return (
            score,
            {
                "liquidity": round(liquidity, 2),
                "fvg_displacement": round(fvg_displacement, 2),
                "htf_alignment": round(htf_alignment, 2),
                "ob_freshness": round(ob_freshness, 2),
                "trend_proxy": round(trend_proxy, 2),
                "zone_age_hours": round(self._zone_age_hours(zone, now=now), 2),
            },
            {key: round(value, 6) for key, value in base_weights.items()},
            {key: round(value, 6) for key, value in active_weights.items()},
            round(zone_type_multiplier, 6),
        )

    def _transition_edge_variant_profile(self, profile: RegimeProfile) -> RegimeProfile:
        if profile.name != "transition":
            return profile
        return RegimeProfile(
            name=profile.name,
            min_confluence=max(
                self._safe_float(self.settings.min_confluence_score, default=62.0),
                float(profile.min_confluence)
                - self._safe_float(self.settings.transition_edge_variant_min_confluence_delta, default=8.0),
            ),
            rr_floor=profile.rr_floor,
            ev_floor=profile.ev_floor,
            weight_liquidity=profile.weight_liquidity,
            weight_fvg_displacement=profile.weight_fvg_displacement,
            weight_htf_alignment=profile.weight_htf_alignment,
            weight_ob_freshness=profile.weight_ob_freshness,
            weight_trend_proxy=profile.weight_trend_proxy,
        )

    def _transition_edge_variant_confluence(
        self,
        *,
        profile: RegimeProfile,
        confluence_components: dict[str, float],
        feature_weights_base: dict[str, float] | None,
        feature_weights_active: dict[str, float] | None,
        zone_type_multiplier: float,
    ) -> tuple[RegimeProfile, float, dict[str, float], dict[str, float], dict[str, float]]:
        variant_profile = self._transition_edge_variant_profile(profile)
        base_weights = dict(feature_weights_base or self.feature_weights_for_regime(profile.name))
        adjusted_weights = dict(feature_weights_active or base_weights)
        adjusted_weights["htf_alignment"] = float(adjusted_weights.get("htf_alignment", 0.0)) * float(
            self._safe_float(self.settings.transition_edge_variant_htf_alignment_weight_multiplier, default=0.5)
        )
        adjusted_weights["trend_proxy"] = float(adjusted_weights.get("trend_proxy", 0.0)) * float(
            self._safe_float(self.settings.transition_edge_variant_trend_proxy_weight_multiplier, default=0.25)
        )
        adjusted_weights = self._normalize_weights(adjusted_weights, min_weight=0.0)

        floor = 45.0
        relax_factor = max(self._safe_float(self.settings.transition_edge_variant_fvg_relax_factor, default=0.7), 1e-6)
        raw_fvg = float(confluence_components.get("fvg_displacement", 0.0))
        fvg_relaxed = clamp(floor + max(raw_fvg - floor, 0.0) / relax_factor, 0.0, 100.0)
        adjusted_components = dict(confluence_components)
        adjusted_components["fvg_displacement"] = round(fvg_relaxed, 2)

        weighted = (
            adjusted_weights.get("liquidity", 0.0) * float(adjusted_components.get("liquidity", 0.0))
            + adjusted_weights.get("fvg_displacement", 0.0) * float(adjusted_components.get("fvg_displacement", 0.0))
            + adjusted_weights.get("htf_alignment", 0.0) * float(adjusted_components.get("htf_alignment", 0.0))
            + adjusted_weights.get("ob_freshness", 0.0) * float(adjusted_components.get("ob_freshness", 0.0))
            + adjusted_weights.get("trend_proxy", 0.0) * float(adjusted_components.get("trend_proxy", 0.0))
        )
        adjusted_score = clamp(weighted * float(zone_type_multiplier or 1.0), 0.0, 100.0)
        return (
            variant_profile,
            adjusted_score,
            adjusted_components,
            {key: round(float(value), 6) for key, value in base_weights.items()},
            {key: round(float(value), 6) for key, value in adjusted_weights.items()},
        )

    def _proof_reclaim_transition_result(
        self,
        *,
        signal: dict[str, Any],
        context: ContextSnapshot,
    ) -> AcceptanceRejectionResult:
        entry_model = str(signal.get("entry_model") or "")
        confirmed = entry_model == EntryModel.LIMIT.value
        session_quality = clamp(
            1.0 - (0.65 * float(context.friction_5m or 0.0) + 0.35 * float(context.jump_rate_5m or 0.0)),
            0.0,
            1.0,
        )
        return AcceptanceRejectionResult(
            available=True,
            classification="rejection_confirmed" if confirmed else "rejection_tentative",
            rejection_score=82.0 if confirmed else 68.0,
            acceptance_score=18.0,
            rejection_hard_count=3 if confirmed else 2,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={
                "shadow_variant": "proof_reclaim",
                "swept_level": float(signal.get("swept_level") or 0.0),
                "sweep_side": str(signal.get("sweep_side") or ""),
                "outside_close_count": 0,
                "session_quality": float(session_quality),
            },
        )

    @staticmethod
    def _is_rejection_reaction(reaction: AcceptanceRejectionResult) -> bool:
        return bool(reaction.available) and str(reaction.classification or "") in {
            "rejection_confirmed",
            "rejection_tentative",
        }

    def _transition_edge_variant_reaction(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        candles_5m: list[Candle] | None,
    ) -> tuple[AcceptanceRejectionResult | None, str]:
        exact_input, _ = self.reaction_classifier.build_input_with_reason(
            zone=zone,
            context=context,
            candles_5m=candles_5m,
        )
        exact_reaction = self.reaction_classifier.classify(exact_input)
        if self._is_rejection_reaction(exact_reaction):
            return exact_reaction, "exact_rejection"

        one_bar_input, _ = self.reaction_classifier.build_input_with_reason(
            zone=zone,
            context=context,
            candles_5m=candles_5m,
            min_event_bars=self._REACTION_SHADOW_ONE_BAR_MIN_EVENT_BARS,
            swept_level_type_override="one_bar_shadow",
        )
        one_bar_reaction = self.reaction_classifier.classify(one_bar_input)
        if self._is_rejection_reaction(one_bar_reaction):
            one_bar_reaction.input = dict(one_bar_reaction.input or {})
            one_bar_reaction.input["shadow_variant"] = "one_bar"
            return one_bar_reaction, "one_bar_shadow"

        proof_signal, proof_reason = self._proof_reclaim_shadow_signal(
            zone=zone,
            context=context,
            candles_5m=candles_5m,
        )
        if proof_signal is not None and str(proof_signal.get("family") or "") == "sweep_reversal":
            return self._proof_reclaim_transition_result(signal=proof_signal, context=context), "proof_reclaim_shadow"
        return None, str(proof_reason or "no_transition_edge_reaction")

    def _transition_edge_variant_candidate(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        candles_5m: list[Candle] | None,
        zone_strength: float,
        near_lp: bool,
        confluence_components: dict[str, float],
        feature_weights_base: dict[str, float],
        feature_weights_active: dict[str, float],
        zone_type_multiplier_active: float,
        profile: RegimeProfile,
    ) -> dict[str, Any] | None:
        if not bool(self.settings.transition_edge_variant_enabled):
            return None
        if profile.name != "transition":
            return None

        reaction, rescue_reason = self._transition_edge_variant_reaction(
            zone=zone,
            context=context,
            candles_5m=candles_5m,
        )
        if reaction is None:
            return None

        variant_profile, variant_score, variant_components, variant_weights_base, variant_weights_active = self._transition_edge_variant_confluence(
            profile=profile,
            confluence_components=confluence_components,
            feature_weights_base=feature_weights_base,
            feature_weights_active=feature_weights_active,
            zone_type_multiplier=zone_type_multiplier_active,
        )
        if variant_score < variant_profile.min_confluence:
            return None

        strategy_family = self.strategy_family_router.route(
            zone=zone,
            context=context,
            reaction=reaction,
            near_lp=near_lp,
            zone_strength=zone_strength,
            confluence_score=variant_score,
            regime_name=variant_profile.name,
            candles_5m=candles_5m,
        )
        if (
            not strategy_family.available
            or strategy_family.family != "sweep_reversal"
            or strategy_family.entry_model != EntryModel.LIMIT
        ):
            return None

        return {
            "reaction": reaction,
            "rescue_reason": rescue_reason,
            "profile": variant_profile,
            "strategy_family": strategy_family,
            "confluence_score": variant_score,
            "confluence_components": variant_components,
            "feature_weights_base": variant_weights_base,
            "feature_weights_active": variant_weights_active,
        }

    def _meta_threshold(self, regime_name: str) -> float:
        if regime_name == "trend":
            return self.settings.meta_filter_min_score_trend
        if regime_name == "shock":
            return self.settings.meta_filter_min_score_shock
        if regime_name == "transition":
            return max(self.settings.meta_filter_min_score_shock, self.settings.min_confluence_score + 16.0)
        return self.settings.meta_filter_min_score_range

    def _meta_filter(
        self,
        *,
        profile: RegimeProfile,
        context: ContextSnapshot,
        reliability: float,
        ev: float,
        rr_base: float,
        rr_floor: float,
        confluence_score: float,
        final_score: float,
        counter_trend: bool,
    ) -> tuple[bool, float, float, str]:
        threshold = self._meta_threshold(profile.name)
        if reliability < self.settings.meta_filter_min_reliability and profile.name != "trend":
            return False, 0.0, threshold, "meta_low_reliability"

        base = (
            40.0
            + (confluence_score - profile.min_confluence) * 0.8
            + (ev - profile.ev_floor) * 28.0
            + (rr_base - rr_floor) * 14.0
            + reliability * 16.0
            + final_score * 0.12
        )
        penalty = context.friction_5m * 18.0 + context.jump_rate_5m * 16.0
        if counter_trend:
            penalty += 8.0
        if profile.name == "shock":
            penalty += 4.0

        meta_score = clamp(base - penalty, 0.0, 100.0)
        if not self.settings.meta_filter_enabled:
            return True, meta_score, threshold, "meta_filter_disabled"
        if meta_score >= threshold:
            return True, meta_score, threshold, "meta_pass"
        return False, meta_score, threshold, "meta_score_below_threshold"

    def _generic_setup_block_reason(
        self,
        *,
        zone: Zone,
        near_lp: bool,
        reaction,
        strategy_family: StrategyFamilyDecision,
        confluence_components: dict[str, float],
        candles_5m: list[Candle] | None,
    ) -> str | None:
        if strategy_family.family != "legacy_zone_plan":
            return None
        if not candles_5m:
            return None
        if near_lp:
            return None

        reaction_missing = (not bool(getattr(reaction, "available", False))) or str(getattr(reaction, "classification", "")) == "not_applicable"
        if not reaction_missing:
            return None

        if zone.type == "OB":
            return "ob_only_block"
        if zone.type == "FVG":
            return "fvg_only_block"

        trend_proxy = float(confluence_components.get("trend_proxy", 0.0))
        liquidity = float(confluence_components.get("liquidity", 0.0))
        fvg_displacement = float(confluence_components.get("fvg_displacement", 0.0))
        ob_freshness = float(confluence_components.get("ob_freshness", 0.0))
        if trend_proxy >= max(liquidity, fvg_displacement, ob_freshness) and trend_proxy >= 65.0:
            return "trendline_led_block"
        return None

    @staticmethod
    def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
        return {str(key): int(value) for key, value in sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))}

    @classmethod
    def _reaction_shadow_zone_band_level(cls, zone: Zone) -> float | None:
        width = max(float(zone.high) - float(zone.low), 0.0)
        if width <= 1e-9:
            return None
        band = width * cls._REACTION_SHADOW_ZONE_BAND_FRACTION
        if str(zone.dir_bias or "") == "support":
            return float(zone.low) + band
        if str(zone.dir_bias or "") == "resistance":
            return float(zone.high) - band
        return None

    def _record_shadow_reaction_lane(
        self,
        *,
        counter: Counter[str],
        lane_prefix: str,
        exact_reason: str,
        zone: Zone,
        context: ContextSnapshot,
        candles_5m: list[Candle] | None,
        near_lp: bool,
        zone_strength: float,
        confluence_score: float,
        regime_name: str,
        sweep_level_override: float | None = None,
        swept_level_type_override: str | None = None,
        min_event_bars: int = 2,
    ) -> None:
        shadow_input, shadow_reason = self.reaction_classifier.build_input_with_reason(
            zone=zone,
            context=context,
            candles_5m=candles_5m,
            sweep_level_override=sweep_level_override,
            swept_level_type_override=swept_level_type_override,
            min_event_bars=min_event_bars,
        )
        if shadow_input is None:
            counter[f"{lane_prefix}:shadow_unavailable:{shadow_reason}"] += 1
            return

        counter[f"{lane_prefix}:shadow_input_available"] += 1
        counter[f"{lane_prefix}:rescued_from:{exact_reason}"] += 1
        shadow_reaction = self.reaction_classifier.classify(shadow_input)
        shadow_classification = str(shadow_reaction.classification or "unknown")
        counter[f"{lane_prefix}:shadow_classification:{shadow_classification}"] += 1

        shadow_strategy_family = self.strategy_family_router.route(
            zone=zone,
            context=context,
            reaction=shadow_reaction,
            near_lp=near_lp,
            zone_strength=zone_strength,
            confluence_score=confluence_score,
            regime_name=regime_name,
            candles_5m=candles_5m,
        )
        if shadow_strategy_family.family != "none":
            counter[f"{lane_prefix}:shadow_family:{shadow_strategy_family.family}"] += 1
        if shadow_strategy_family.available:
            counter[f"{lane_prefix}:shadow_available_family"] += 1
            counter[
                f"{lane_prefix}:shadow_available_family:{shadow_strategy_family.family}"
            ] += 1
            if shadow_strategy_family.entry_model is not None:
                counter[
                    f"{lane_prefix}:shadow_available_entry_model:{shadow_strategy_family.entry_model.value}"
                ] += 1

    def _proof_reclaim_shadow_signal(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        candles_5m: list[Candle] | None,
    ) -> tuple[dict[str, Any] | None, str]:
        if not candles_5m:
            return None, "insufficient_candles"
        total_bars = int(self._PROOF_RECLAIM_LOOKBACK_TOTAL_BARS)
        exclude_recent = int(self._PROOF_RECLAIM_EXCLUDE_RECENT_BARS)
        if len(candles_5m) < total_bars:
            return None, "insufficient_candles"

        prior_window = candles_5m[-total_bars:-exclude_recent]
        if not prior_window:
            return None, "insufficient_prior_window"

        atr15 = float(context.atr15 or 0.0)
        if atr15 <= 1e-9:
            return None, "insufficient_atr"

        latest = candles_5m[-1]
        latest_high = float(latest.h)
        latest_low = float(latest.l)
        latest_close = float(latest.c)
        latest_range = max(latest_high - latest_low, 1e-9)
        close_position = (latest_close - latest_low) / latest_range
        sweep_threshold = atr15 * float(self._PROOF_RECLAIM_SWEEP_ATR_THRESHOLD)

        if str(zone.dir_bias or "") == "support":
            prior_level = min(float(c.l) for c in prior_window)
            if latest_low < prior_level - sweep_threshold and latest_close > prior_level and close_position >= 0.4:
                entry_model = (
                    EntryModel.LIMIT
                    if close_position >= 0.68
                    else EntryModel.SWEEP_CONFIRM
                    if close_position >= 0.52
                    else EntryModel.CONFIRM
                )
                return {
                    "family": "sweep_reversal",
                    "direction": "long",
                    "entry_model": entry_model.value,
                    "swept_level": round(prior_level, 6),
                }, "ok"
            return None, "proof_reclaim_not_met"

        if str(zone.dir_bias or "") == "resistance":
            prior_level = max(float(c.h) for c in prior_window)
            if latest_high > prior_level + sweep_threshold and latest_close < prior_level and close_position <= 0.6:
                entry_model = (
                    EntryModel.LIMIT
                    if close_position <= 0.32
                    else EntryModel.SWEEP_CONFIRM
                    if close_position <= 0.48
                    else EntryModel.CONFIRM
                )
                return {
                    "family": "sweep_reversal",
                    "direction": "short",
                    "entry_model": entry_model.value,
                    "swept_level": round(prior_level, 6),
                }, "ok"
            return None, "proof_reclaim_not_met"

        return None, "unsupported_zone_direction"

    def generation_diagnostics(
        self,
        *,
        symbol: str,
        zones: list[Zone],
        context: ContextSnapshot,
        candles_5m: list[Candle] | None = None,
        importance_calibration: dict[str, dict] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        profile = self._regime_profile(context)
        mode_policy = self.strategy_mode.policy()
        hard_gate_counts: Counter[str] = Counter()
        transition_edge_variant_counts: Counter[str] = Counter()
        setup_disable_counts: Counter[str] = Counter()
        reaction_skip_counts: Counter[str] = Counter()
        reaction_unavailable_reason_counts: Counter[str] = Counter()
        reaction_shadow_zone_band_counts: Counter[str] = Counter()
        reaction_shadow_one_bar_counts: Counter[str] = Counter()
        reaction_shadow_proof_reclaim_counts: Counter[str] = Counter()
        router_block_counts: Counter[str] = Counter()
        legacy_router_reason_counts: Counter[str] = Counter()
        generic_setup_block_counts: Counter[str] = Counter()
        mode_block_counts: Counter[str] = Counter()
        block_examples: list[dict[str, Any]] = []
        post_hard_gate_zone_count = 0
        pre_generation_candidate_count = 0
        transition_edge_variant_evaluated_count = 0
        transition_edge_variant_expected_ev_sum = 0.0
        transition_edge_variant_expected_ev_count = 0

        for zone in zones:
            stats = dict(zone.stats or {})
            disabled_reason = self._is_setup_disabled(stats)
            if disabled_reason:
                setup_disable_counts[disabled_reason] += 1
                if len(block_examples) < 8:
                    block_examples.append(
                        {
                            "zone_id": zone.zone_id,
                            "stage": "setup_disable",
                            "reason": disabled_reason,
                            "zone_type": zone.type,
                            "dir_bias": zone.dir_bias,
                        }
                    )
                continue

            near_lp = self._find_near_lp(zone, zones, context.atr15)
            confluence_score, confluence_components, *_ = self._confluence_score(
                zone,
                context,
                near_lp,
                stats,
                profile,
                now,
                importance_calibration=importance_calibration,
            )
            gate_reason = self._hard_gate(zone, context, confluence_score, profile)
            if gate_reason is not None:
                if gate_reason == "low_confluence":
                    transition_edge_variant_evaluated_count += 1
                    variant_candidate = self._transition_edge_variant_candidate(
                        zone=zone,
                        context=context,
                        candles_5m=candles_5m,
                        zone_strength=self._zone_strength(zone, context),
                        near_lp=near_lp,
                        confluence_components=confluence_components,
                        feature_weights_base=self.feature_weights_for_regime(profile.name),
                        feature_weights_active=self.feature_weights_for_regime(profile.name),
                        zone_type_multiplier_active=1.0,
                        profile=profile,
                    )
                    if variant_candidate is not None:
                        transition_edge_variant_counts["eligible_shadow_rescue"] += 1
                        transition_edge_variant_counts[f"rescue_reason:{variant_candidate['rescue_reason']}"] += 1
                        transition_edge_variant_counts[f"family:{variant_candidate['strategy_family'].family}"] += 1
                        transition_edge_variant_expected_ev_sum += float(stats.get("ev_r", 0.0) or 0.0)
                        transition_edge_variant_expected_ev_count += 1
                hard_gate_counts[gate_reason] += 1
                if len(block_examples) < 8:
                    block_examples.append(
                        {
                            "zone_id": zone.zone_id,
                            "stage": "hard_gate",
                            "reason": gate_reason,
                            "zone_type": zone.type,
                            "dir_bias": zone.dir_bias,
                            "confluence_score": round(float(confluence_score), 2),
                        }
                    )
                continue
            post_hard_gate_zone_count += 1

            reaction_input, reaction_input_reason = self.reaction_classifier.build_input_with_reason(
                zone=zone,
                context=context,
                candles_5m=candles_5m,
            )
            reaction = self.reaction_classifier.classify(reaction_input)
            classification = str(reaction.classification)
            if not reaction.available:
                reaction_unavailable_reason_counts[reaction_input_reason] += 1
                reaction_shadow_zone_band_counts["exact_unavailable_zones"] += 1
                shadow_level = self._reaction_shadow_zone_band_level(zone)
                if shadow_level is not None:
                    self._record_shadow_reaction_lane(
                        counter=reaction_shadow_zone_band_counts,
                        lane_prefix="zone_band",
                        exact_reason=reaction_input_reason,
                        zone=zone,
                        context=context,
                        candles_5m=candles_5m,
                        near_lp=near_lp,
                        zone_strength=self._zone_strength(zone, context),
                        confluence_score=confluence_score,
                        regime_name=profile.name,
                        sweep_level_override=shadow_level,
                        swept_level_type_override="zone_band_shadow",
                    )

                if reaction_input_reason == "insufficient_post_sweep_bars":
                    reaction_shadow_one_bar_counts["exact_insufficient_post_sweep_zones"] += 1
                    self._record_shadow_reaction_lane(
                        counter=reaction_shadow_one_bar_counts,
                        lane_prefix="one_bar",
                        exact_reason=reaction_input_reason,
                        zone=zone,
                        context=context,
                        candles_5m=candles_5m,
                        near_lp=near_lp,
                        zone_strength=self._zone_strength(zone, context),
                        confluence_score=confluence_score,
                        regime_name=profile.name,
                        min_event_bars=self._REACTION_SHADOW_ONE_BAR_MIN_EVENT_BARS,
                        swept_level_type_override="one_bar_shadow",
                    )

                reaction_shadow_proof_reclaim_counts["exact_unavailable_zones"] += 1
                proof_shadow_signal, proof_shadow_reason = self._proof_reclaim_shadow_signal(
                    zone=zone,
                    context=context,
                    candles_5m=candles_5m,
                )
                if proof_shadow_signal is None:
                    reaction_shadow_proof_reclaim_counts[
                        f"proof_reclaim_unavailable:{proof_shadow_reason}"
                    ] += 1
                else:
                    reaction_shadow_proof_reclaim_counts["proof_reclaim_signal_detected"] += 1
                    reaction_shadow_proof_reclaim_counts[
                        f"rescued_from:{reaction_input_reason}"
                    ] += 1
                    reaction_shadow_proof_reclaim_counts[
                        f"proof_reclaim_family:{proof_shadow_signal['family']}"
                    ] += 1
                    reaction_shadow_proof_reclaim_counts[
                        f"proof_reclaim_entry_model:{proof_shadow_signal['entry_model']}"
                    ] += 1
            if reaction.available and classification == "mixed":
                reaction_skip_counts["mixed"] += 1
                if len(block_examples) < 8:
                    block_examples.append(
                        {
                            "zone_id": zone.zone_id,
                            "stage": "reaction_skip",
                            "reason": "mixed",
                            "zone_type": zone.type,
                            "dir_bias": zone.dir_bias,
                        }
                    )
                continue
            if reaction.available and classification in {"acceptance_confirmed", "acceptance_tentative"}:
                reaction_skip_counts[classification] += 1
                if len(block_examples) < 8:
                    block_examples.append(
                        {
                            "zone_id": zone.zone_id,
                            "stage": "reaction_skip",
                            "reason": classification,
                            "zone_type": zone.type,
                            "dir_bias": zone.dir_bias,
                        }
                    )
                continue

            strategy_family = StrategyFamilyDecision(
                available=False,
                family="legacy_zone_plan",
                grade="F",
                score=0.0,
                reason="strategy_family_not_applicable",
                entry_model=None,
            )
            routed_family = self.strategy_family_router.route(
                zone=zone,
                context=context,
                reaction=reaction,
                near_lp=near_lp,
                zone_strength=self._zone_strength(zone, context),
                confluence_score=confluence_score,
                regime_name=profile.name,
                candles_5m=candles_5m,
            )
            if routed_family.family != "none":
                strategy_family = routed_family
                if not strategy_family.available:
                    router_block_counts[str(strategy_family.reason or strategy_family.family)] += 1
                    if len(block_examples) < 8:
                        block_examples.append(
                            {
                                "zone_id": zone.zone_id,
                                "stage": "router_block",
                                "reason": str(strategy_family.reason or strategy_family.family),
                                "zone_type": zone.type,
                                "dir_bias": zone.dir_bias,
                            }
                        )
                    continue
            elif str(routed_family.reason or "").strip():
                legacy_router_reason = str(routed_family.reason)
                legacy_router_reason_counts[legacy_router_reason] += 1
                strategy_family = StrategyFamilyDecision(
                    available=False,
                    family="legacy_zone_plan",
                    grade="F",
                    score=0.0,
                    reason=legacy_router_reason,
                    entry_model=None,
                )

            generic_block_reason = self._generic_setup_block_reason(
                zone=zone,
                near_lp=near_lp,
                reaction=reaction,
                strategy_family=strategy_family,
                confluence_components=confluence_components,
                candles_5m=candles_5m,
            )
            if generic_block_reason:
                generic_setup_block_counts[generic_block_reason] += 1
                if len(block_examples) < 8:
                    block_examples.append(
                        {
                            "zone_id": zone.zone_id,
                            "stage": "generic_setup_block",
                            "reason": generic_block_reason,
                            "zone_type": zone.type,
                            "dir_bias": zone.dir_bias,
                        }
                    )
                continue

            mode_allowed, mode_reason = self.strategy_mode.allow_candidate(
                strategy_family=strategy_family.family,
                strategy_grade=strategy_family.grade if strategy_family.available else None,
                mode=mode_policy.mode,
            )
            if not mode_allowed:
                mode_block_counts[str(mode_reason or "mode_rejected")] += 1
                if len(block_examples) < 8:
                    block_examples.append(
                        {
                            "zone_id": zone.zone_id,
                            "stage": "mode_block",
                            "reason": str(mode_reason or "mode_rejected"),
                            "zone_type": zone.type,
                            "dir_bias": zone.dir_bias,
                        }
                    )
                continue

            pre_generation_candidate_count += 1

        low_confluence_block_count = int(hard_gate_counts.get("low_confluence", 0) or 0)
        shadow_pass_count = int(transition_edge_variant_counts.get("eligible_shadow_rescue", 0) or 0)
        rescue_reason_mix = {
            str(key).split("rescue_reason:", 1)[1]: int(value)
            for key, value in transition_edge_variant_counts.items()
            if str(key).startswith("rescue_reason:")
        }
        transition_edge_variant_shadow_summary = {
            "available": bool(self.settings.transition_edge_variant_enabled),
            "shadow_only": bool(self.settings.transition_edge_variant_shadow_only),
            "variant": "exp_6_fvg_relaxed_plus_transition_override",
            "evaluated": int(transition_edge_variant_evaluated_count),
            "pass": shadow_pass_count,
            "pass_rate": round(
                shadow_pass_count / max(int(transition_edge_variant_evaluated_count), 1),
                4,
            )
            if transition_edge_variant_evaluated_count > 0
            else 0.0,
            "reason_mix": rescue_reason_mix,
            "candidate_baseline": int(pre_generation_candidate_count),
            "candidate_shadow": int(pre_generation_candidate_count + shadow_pass_count),
            "shadow_candidate_delta": int(shadow_pass_count),
            "low_confluence_block_baseline": low_confluence_block_count,
            "low_confluence_block_shadow": max(low_confluence_block_count - shadow_pass_count, 0),
            "low_confluence_block_delta": -int(shadow_pass_count),
            "expected_ev_r_proxy": round(
                transition_edge_variant_expected_ev_sum / max(transition_edge_variant_expected_ev_count, 1),
                4,
            )
            if transition_edge_variant_expected_ev_count > 0
            else 0.0,
        }

        return {
            "schema_version": "plan_generation_diagnostics_v1",
            "symbol": symbol,
            "generation_state": "diagnosed",
            "regime_profile": profile.name,
            "transition_state": context.transition_state,
            "transition_lock_reason": context.transition_lock_reason,
            "active_zone_count": len(zones),
            "post_hard_gate_zone_count": int(post_hard_gate_zone_count),
            "pre_generation_candidate_count": int(pre_generation_candidate_count),
            "setup_disable_counts": self._sorted_counts(setup_disable_counts),
            "hard_gate_block_counts": self._sorted_counts(hard_gate_counts),
            "transition_edge_variant_shadow_counts": self._sorted_counts(transition_edge_variant_counts),
            "transition_edge_variant_shadow_summary": transition_edge_variant_shadow_summary,
            "reaction_unavailable_reason_counts": self._sorted_counts(reaction_unavailable_reason_counts),
            "reaction_shadow_zone_band_counts": self._sorted_counts(reaction_shadow_zone_band_counts),
            "reaction_shadow_one_bar_counts": self._sorted_counts(reaction_shadow_one_bar_counts),
            "reaction_shadow_proof_reclaim_counts": self._sorted_counts(reaction_shadow_proof_reclaim_counts),
            "reaction_skip_counts": self._sorted_counts(reaction_skip_counts),
            "router_block_counts": self._sorted_counts(router_block_counts),
            "legacy_router_reason_counts": self._sorted_counts(legacy_router_reason_counts),
            "generic_setup_block_counts": self._sorted_counts(generic_setup_block_counts),
            "mode_block_counts": self._sorted_counts(mode_block_counts),
            "block_examples": block_examples,
        }

    def _hard_gate(self, zone: Zone, context: ContextSnapshot, confluence_score: float, profile: RegimeProfile) -> str | None:
        counter_trend = (zone.dir_bias == "support" and context.v < 0) or (zone.dir_bias == "resistance" and context.v > 0)

        if confluence_score < profile.min_confluence:
            return "low_confluence"
        if context.friction_5m >= self.settings.friction_hard_gate:
            return "friction_hard_gate"
        if context.jump_rate_5m >= self.settings.jump_hard_gate:
            return "jump_hard_gate"
        if context.transition_state == "transition_confirmed":
            return context.transition_lock_reason or "transition_lock"
        if counter_trend and context.regime_15m >= self.settings.strong_regime_gate and profile.name != "range":
            return "strong_regime_counter_trend"
        if profile.name == "shock" and zone.type == "FLIP":
            return "shock_flip_block"
        return None

    def _reliability_factor(self, stats: dict) -> float:
        sample = float(stats.get("sample_size", 0.0))
        return clamp(sample / max(self.settings.min_zone_sample_for_full_confidence, 1), 0.20, 1.0)

    def _dedupe_ranked(self, ranked: list[RankedPlan], atr15: float) -> list[RankedPlan]:
        if not ranked:
            return []

        out: list[RankedPlan] = []
        min_dist = atr15 * self.settings.dedupe_entry_atr_distance
        for candidate in ranked:
            conflict = False
            for chosen in out:
                same_symbol = chosen.plan.symbol == candidate.plan.symbol
                same_side = chosen.plan.direction == candidate.plan.direction
                too_close = abs(chosen.plan.entry_price - candidate.plan.entry_price) <= min_dist
                if same_symbol and same_side and too_close:
                    conflict = True
                    break
            if not conflict:
                out.append(candidate)
            if len(out) >= self.settings.max_candidate_plans_per_symbol:
                break
        return out

    @staticmethod
    def _rr(direction: Direction, entry: float, sl: float, tp: float) -> float:
        risk = abs(entry - sl)
        if risk <= 1e-9:
            return 0.0
        reward = (tp - entry) if direction == Direction.LONG else (entry - tp)
        return reward / risk

    def _targets(self, direction: Direction, entry: float, sl: float, zone: Zone, zones: list[Zone]) -> tuple[float, float, float]:
        risk = abs(entry - sl)
        if direction == Direction.LONG:
            opposite = sorted([z.mid for z in zones if z.dir_bias == "resistance" and z.mid > entry])
            lp_targets = sorted([z.mid for z in zones if z.type == "LP" and z.mid > entry])
            tp1 = min(opposite[0], entry + risk * 1.0) if opposite else entry + risk * 1.0
            tp2 = min(lp_targets[0], entry + risk * 2.0) if lp_targets else entry + risk * 2.0
            tp3 = max(opposite[1], entry + risk * 3.0) if len(opposite) > 1 else entry + risk * 3.0
            return tp1, tp2, tp3

        opposite = sorted([z.mid for z in zones if z.dir_bias == "support" and z.mid < entry], reverse=True)
        lp_targets = sorted([z.mid for z in zones if z.type == "LP" and z.mid < entry], reverse=True)
        tp1 = max(opposite[0], entry - risk * 1.0) if opposite else entry - risk * 1.0
        tp2 = max(lp_targets[0], entry - risk * 2.0) if lp_targets else entry - risk * 2.0
        tp3 = min(opposite[1], entry - risk * 3.0) if len(opposite) > 1 else entry - risk * 3.0
        return tp1, tp2, tp3

    @staticmethod
    def _split(stats: dict, friction: float) -> dict[str, float]:
        p1 = float(stats.get("p1r", 0.55))
        p3 = float(stats.get("p3r", 0.25))

        tp1 = clamp(0.60 + 0.10 * p1 + 0.10 * friction, 0.60, 0.75)
        runner = clamp(0.10 + 0.20 * p3 - 0.10 * friction, 0.05, 0.30)
        tp2 = 1.0 - tp1 - runner
        tp2 = clamp(tp2, 0.15, 0.35)

        total = tp1 + tp2 + runner
        return {
            "tp1": tp1 / total,
            "tp2": tp2 / total,
            "runner": runner / total,
        }

    def _cost_in_r(self, model: EntryModel, entry: float, sl: float, friction: float) -> float:
        fee_bps = self.settings.maker_fee_bps if model == EntryModel.LIMIT else self.settings.taker_fee_bps
        slippage_bps = self.settings.slippage_bps_base + self.settings.slippage_bps_k * friction
        total_bps = fee_bps * 2.0 + slippage_bps

        risk_abs = abs(entry - sl)
        if risk_abs <= 1e-9:
            return 1.0
        cost_abs = entry * (total_bps / 10000.0)
        return cost_abs / risk_abs

    @staticmethod
    def _grade_probability_boost(grade: str | None) -> float:
        mapping = {
            "A": 0.035,
            "B": 0.015,
            "C": -0.010,
        }
        return float(mapping.get(str(grade or "").upper(), 0.0))

    @staticmethod
    def _reaction_probability_boost(classification: str) -> float:
        mapping = {
            "rejection_confirmed": 0.030,
            "rejection_tentative": 0.012,
            "not_applicable": 0.0,
        }
        return float(mapping.get(str(classification or ""), 0.0))

    @staticmethod
    def _entry_model_probability_boost(model: EntryModel) -> float:
        mapping = {
            EntryModel.SWEEP_CONFIRM: 0.015,
            EntryModel.CONFIRM: 0.008,
            EntryModel.LIMIT: -0.006,
        }
        return float(mapping.get(model, 0.0))

    def _expected_probability_adjustment(
        self,
        *,
        context: ContextSnapshot,
        regime: RegimeProfile,
        strategy_family: StrategyFamilyDecision,
        reaction_classification: str,
        decision: EntryDecision,
        confluence_score: float,
        near_lp: bool,
        reliability: float,
        session_adjustment: float,
    ) -> tuple[float, dict[str, float]]:
        components = {
            "grade": self._grade_probability_boost(strategy_family.grade if strategy_family.available else "B"),
            "reaction": self._reaction_probability_boost(reaction_classification),
            "entry_model": self._entry_model_probability_boost(decision.model),
            "confluence": clamp((confluence_score - regime.min_confluence) / 100.0 * 0.12, -0.015, 0.045),
            "near_lp": 0.010 if near_lp else 0.0,
            "friction": clamp(-float(context.friction_5m) * 0.045, -0.030, 0.0),
            "transition": -0.025 if context.transition_state == "transition_watch" else 0.0,
            "regime": (
                0.012
                if regime.name == "trend"
                else -0.020
                if regime.name == "shock"
                else -0.028
                if regime.name == "transition"
                else 0.0
            ),
            "session": session_adjustment,
        }
        raw = sum(components.values())
        low_sample_weight = clamp(1.10 - reliability * 0.80, 0.30, 1.0)
        adjusted = clamp(raw * low_sample_weight, -0.070, 0.070)
        rounded = {key: round(float(value), 4) for key, value in components.items()}
        rounded["low_sample_weight"] = round(low_sample_weight, 4)
        rounded["applied_adjustment"] = round(adjusted, 4)
        return adjusted, rounded

    def generate(
        self,
        symbol: str,
        zones: list[Zone],
        context: ContextSnapshot,
        candles_5m: list[Candle] | None = None,
        feature_overrides: dict[str, float] | None = None,
        importance_calibration: dict[str, dict] | None = None,
        active_thesis_clusters: int = 0,
        now: datetime | None = None,
    ) -> list[RankedPlan]:
        now = now or datetime.now(timezone.utc)
        out: list[RankedPlan] = []
        regime = self._regime_profile(context)
        mode_policy = self.strategy_mode.policy()
        session_guidance = self.session_guidance.snapshot(strategy_mode=mode_policy.mode, now=now)
        session_state = str(session_guidance.get("state", "unknown"))
        session_name = str((session_guidance.get("current_session") or {}).get("name") or "inactive").strip().lower() or "inactive"
        if session_state == "preferred_live_window":
            session_score_bias = self._safe_float(self.settings.scalp_session_boost_score, default=4.0)
            session_probability_adjustment = 0.012
        elif session_state == "session_lock_active":
            session_score_bias = -self._safe_float(self.settings.scalp_session_lock_penalty_score, default=3.0)
            session_probability_adjustment = -0.010
        else:
            session_score_bias = -self._safe_float(self.settings.scalp_dead_session_penalty_score, default=6.0)
            session_probability_adjustment = -0.018

        for zone in zones:
            if zone.state == "expired":
                continue
            if self._zone_is_stale_for_scalp(zone, now=now):
                continue

            stats = zone.stats or {}
            disabled_reason = self._is_setup_disabled(stats)
            if disabled_reason:
                continue

            direction = self._direction(zone)
            zs = self._zone_strength(zone, context)
            approach = self._approach_score(zone, context)
            near_lp = self._find_near_lp(zone, zones, context.atr15)
            (
                confluence_score,
                confluence_components,
                feature_weights_base,
                feature_weights_active,
                zone_type_multiplier_active,
            ) = self._confluence_score(
                zone,
                context,
                near_lp,
                stats,
                regime,
                now,
                feature_overrides=feature_overrides,
                importance_calibration=importance_calibration,
            )
            zone_profile = regime
            transition_edge_variant: dict[str, Any] | None = None
            transition_edge_variant_shadow = False
            strategy_family_override: StrategyFamilyDecision | None = None
            reaction_override: AcceptanceRejectionResult | None = None
            gate_reason = self._hard_gate(zone, context, confluence_score, zone_profile)
            if gate_reason == "low_confluence":
                transition_edge_variant = self._transition_edge_variant_candidate(
                    zone=zone,
                    context=context,
                    candles_5m=candles_5m,
                    zone_strength=zs,
                    near_lp=near_lp,
                    confluence_components=confluence_components,
                    feature_weights_base=feature_weights_base,
                    feature_weights_active=feature_weights_active,
                    zone_type_multiplier_active=zone_type_multiplier_active,
                    profile=zone_profile,
                )
                if transition_edge_variant is not None:
                    transition_edge_variant_shadow = bool(self.settings.transition_edge_variant_shadow_only)
                    if not transition_edge_variant_shadow:
                        zone_profile = transition_edge_variant["profile"]
                        confluence_score = float(transition_edge_variant["confluence_score"])
                        confluence_components = dict(transition_edge_variant["confluence_components"])
                        feature_weights_base = dict(transition_edge_variant["feature_weights_base"])
                        feature_weights_active = dict(transition_edge_variant["feature_weights_active"])
                        strategy_family_override = transition_edge_variant["strategy_family"]
                        reaction_override = transition_edge_variant["reaction"]
                        gate_reason = self._hard_gate(zone, context, confluence_score, zone_profile)
            if gate_reason is not None:
                continue

            reaction = reaction_override or self.reaction_classifier.classify_zone(zone=zone, context=context, candles_5m=candles_5m)
            if reaction.available and reaction.classification == "mixed":
                continue
            if reaction.available and reaction.classification in {"acceptance_confirmed", "acceptance_tentative"}:
                continue

            strategy_family = strategy_family_override or StrategyFamilyDecision(
                available=False,
                family="legacy_zone_plan",
                grade="F",
                score=0.0,
                reason="strategy_family_not_applicable",
                entry_model=None,
            )
            if strategy_family_override is None:
                routed_family = self.strategy_family_router.route(
                    zone=zone,
                    context=context,
                    reaction=reaction,
                    near_lp=near_lp,
                    zone_strength=zs,
                    confluence_score=confluence_score,
                    regime_name=zone_profile.name,
                    candles_5m=candles_5m,
                )
                if routed_family.family != "none":
                    strategy_family = routed_family
                    if not strategy_family.available:
                        continue
                elif str(routed_family.reason or "").strip():
                    strategy_family = StrategyFamilyDecision(
                        available=False,
                        family="legacy_zone_plan",
                        grade="F",
                        score=0.0,
                        reason=str(routed_family.reason),
                        entry_model=None,
                    )
            generic_block_reason = self._generic_setup_block_reason(
                zone=zone,
                near_lp=near_lp,
                reaction=reaction,
                strategy_family=strategy_family,
                confluence_components=confluence_components,
                candles_5m=candles_5m,
            )
            if generic_block_reason:
                continue
            mode_allowed, mode_reason = self.strategy_mode.allow_candidate(
                strategy_family=strategy_family.family,
                strategy_grade=strategy_family.grade if strategy_family.available else None,
                mode=mode_policy.mode,
            )
            if not mode_allowed:
                continue

            if strategy_family.available and strategy_family.entry_model is not None:
                decision = EntryDecision(model=strategy_family.entry_model, reason=strategy_family.reason)
            else:
                decision = self.router.choose(zone, context, zs, near_lp, confluence_score=confluence_score)
                if zone_profile.name == "shock" and decision.model == EntryModel.LIMIT:
                    decision = EntryDecision(model=EntryModel.CONFIRM, reason="shock_regime_no_limit")
                if context.transition_state == "transition_watch" and decision.model == EntryModel.LIMIT:
                    decision = EntryDecision(model=EntryModel.CONFIRM, reason="transition_watch_confirm_only")
                if reaction.available and reaction.classification == "rejection_tentative" and decision.model == EntryModel.LIMIT:
                    decision = EntryDecision(model=EntryModel.CONFIRM, reason="rejection_tentative_confirm_only")

            entry = zone.mid
            buffer_mult = 0.5 if decision.model == EntryModel.SWEEP_CONFIRM else 0.3
            if direction == Direction.LONG:
                sl = zone.low - buffer_mult * context.atr5
            else:
                sl = zone.high + buffer_mult * context.atr5

            tp1, tp2, tp3 = self._targets(direction, entry, sl, zone, zones)
            rr1 = self._rr(direction, entry, sl, tp1)
            rr2 = self._rr(direction, entry, sl, tp2)
            rr3 = self._rr(direction, entry, sl, tp3)
            # rr_min excludes TP1 because TP1 is a partial insurance take-profit.
            rr_min = min(rr2, rr3)
            rr_base = rr2
            rr_opt = max(rr1, rr2, rr3)

            reliability = self._reliability_factor(stats)
            p2 = float(stats.get("p2r", 0.40))
            p1 = float(stats.get("p1r", 0.55))
            ev_r = float(stats.get("ev_r", 0.0))
            prior_prob = (
                0.50
                if zone_profile.name == "trend"
                else 0.40
                if zone_profile.name == "shock"
                else 0.36
                if zone_profile.name == "transition"
                else 0.46
            )
            learned_prob = clamp(p2 + 0.12 * p1 + 0.08 * max(0.0, ev_r), 0.20, 0.88)
            base_win_prob = clamp(prior_prob * (1.0 - reliability) + learned_prob * reliability, 0.20, 0.86)
            win_prob_adjustment, win_prob_components = self._expected_probability_adjustment(
                context=context,
                regime=zone_profile,
                strategy_family=strategy_family,
                reaction_classification=reaction.classification,
                decision=decision,
                confluence_score=confluence_score,
                near_lp=near_lp,
                reliability=reliability,
                session_adjustment=session_probability_adjustment,
            )
            win_prob = clamp(base_win_prob + win_prob_adjustment, 0.20, 0.86)
            p1_est = clamp(p1 + win_prob_adjustment * 0.75, 0.35, 0.92)
            p2_raw = clamp(p2 + win_prob_adjustment * 0.60, 0.18, 0.82)
            p2_est = clamp(min(p2_raw, p1_est - 0.03), 0.18, 0.82)
            p3_base = float(stats.get("p3r", 0.25))
            p3_raw = clamp(p3_base + win_prob_adjustment * 0.45, 0.10, 0.65)
            p3_est = clamp(min(p3_raw, p2_est - 0.03), 0.10, 0.65)

            cost_est = self._cost_in_r(decision.model, entry, sl, context.friction_5m)
            ev = win_prob * rr_base - (1.0 - win_prob) * 1.0 - cost_est
            rr_floor = max(self.settings.min_rr, zone_profile.rr_floor)
            if ev <= zone_profile.ev_floor or rr_min < rr_floor:
                continue

            split = strategy_family.split if strategy_family.available and strategy_family.split else self._split(stats, context.friction_5m)
            plan_score = clamp(50 + rr_base * 12 + ev * 15, 0, 100)
            if strategy_family.available:
                plan_score = clamp(plan_score * 0.55 + strategy_family.score * 0.45, 0, 100)

            counter_trend = (zone.dir_bias == "support" and context.v < 0) or (zone.dir_bias == "resistance" and context.v > 0)
            counter_trend_penalty = 0.0
            if counter_trend:
                counter_trend_penalty = context.regime_15m * 10

            friction_penalty = context.friction_5m * 8
            width_penalty = max(0.0, zone.width_atr - 0.9) * 5
            penalties = friction_penalty + width_penalty + counter_trend_penalty
            if zone_profile.name == "shock":
                penalties += 4.0
            if context.transition_state == "transition_watch":
                penalties += 6.0

            final_score = 0.40 * confluence_score + 0.30 * zs + 0.20 * approach + 0.10 * plan_score - penalties + session_score_bias
            confidence = clamp(final_score / 100.0, 0.0, 1.0)
            meta_pass, meta_score, meta_threshold, meta_reason = self._meta_filter(
                profile=zone_profile,
                context=context,
                reliability=reliability,
                ev=ev,
                rr_base=rr_base,
                rr_floor=rr_floor,
                confluence_score=confluence_score,
                final_score=final_score,
                counter_trend=counter_trend,
            )
            if not meta_pass:
                continue

            dist_atr = abs(context.last_price - zone.mid) / max(context.atr15, 1e-9)
            state = PlanState.ARMED.value if dist_atr <= 1.0 else PlanState.PLANNED.value
            thesis_fingerprint = self.thesis.build(
                symbol=symbol,
                direction=direction.value,
                regime=zone_profile.name,
                strategy_family=strategy_family.family,
                reaction_classification=reaction.classification,
                zone_type=zone.type,
                near_lp=near_lp,
                at=now,
            )
            location_reference = self._build_location_reference(
                zone=zone,
                context=context,
                entry_price=entry,
                thesis_fingerprint=thesis_fingerprint,
                near_lp=near_lp,
            )
            session_liquidity_reference = self._build_session_liquidity_reference(
                zone=zone,
                reaction_classification=reaction.classification,
                reaction_input=dict(reaction.input or {}),
                thesis_fingerprint=thesis_fingerprint,
                near_lp=near_lp,
                now=now,
            )
            reaction_evidence = self._build_reaction_evidence(
                reaction_classification=reaction.classification,
                reaction_input=dict(reaction.input or {}),
            )
            runtime_signal_telemetry = self._build_runtime_signal_telemetry(
                context=context,
                zone=zone,
                direction=direction,
                strategy_family=str(strategy_family.family),
                entry_price=entry,
                sl=sl,
                location_reference=location_reference,
            )
            thesis_cluster_id = self.thesis.thesis_cluster_id(thesis_fingerprint)
            confirm_only = bool(strategy_family.confirm_only) or (
                not strategy_family.available and decision.model == EntryModel.CONFIRM
            )
            strategy_sizing = self.sizing.evaluate(
                PositionSizingInput(
                    strategy_family=strategy_family.family,
                    strategy_grade=strategy_family.grade if strategy_family.available else None,
                    regime=zone_profile.name,
                    reaction_classification=reaction.classification,
                    confirm_only=confirm_only,
                    entry_model=decision.model.value,
                    active_thesis_clusters=active_thesis_clusters,
                    transition_state=context.transition_state,
                    symbol=symbol,
                    direction=direction.value,
                )
            )
            runtime_signal_shadow_tilt = self._build_runtime_signal_shadow_tilt(
                symbol=symbol,
                strategy_family=str(strategy_family.family),
                entry_model=decision.model,
                direction=direction,
                runtime_signal_telemetry=runtime_signal_telemetry,
                base_recommended_risk_r=float(strategy_sizing.get("final_risk_r", 0.0) or 0.0),
                expected_ev_r=float(ev),
            )
            if runtime_signal_shadow_tilt is not None:
                strategy_sizing = dict(strategy_sizing)
                strategy_sizing["runtime_signal_shadow_tilt"] = runtime_signal_shadow_tilt
            strategy_sizing = self.strategy_mode.apply_to_sizing(strategy_sizing, mode=mode_policy.mode)
            expected_ev_at_recommended_size_r = float(strategy_sizing.get("final_risk_r", 0.0) or 0.0) * float(ev)
            expected_summary = (
                f"win≈{win_prob * 100.0:.1f}%, "
                f"EV≈{ev:+.2f}R, "
                f"TP1≈{p1_est * 100.0:.1f}%, "
                f"TP2≈{p2_est * 100.0:.1f}%, "
                f"TP3≈{p3_est * 100.0:.1f}%"
            )

            validity_minutes = self._safe_int(self.settings.scalp_plan_validity_minutes, default=90)
            if decision.model == EntryModel.LIMIT:
                validity_minutes -= 20
            elif decision.model == EntryModel.SWEEP_CONFIRM:
                validity_minutes += 10
            if session_state == "dead_session":
                validity_minutes -= 15
            elif session_state == "session_lock_active":
                validity_minutes -= 10
            validity_minutes = max(30, min(120, validity_minutes))

            validity = {
                "regime": zone_profile.name,
                "regime_min": 0.0,
                "friction_max": 0.85,
                "jump_rate_max": 0.35,
                "entry_reason": decision.reason,
                "strategy_family": strategy_family.family,
                "strategy_grade": strategy_family.grade if strategy_family.available else None,
                "strategy_family_score": round(strategy_family.score, 2) if strategy_family.available else None,
                "strategy_family_reason": strategy_family.reason,
                "strategy_family_components": dict(strategy_family.components or {}),
                "strategy_scorecard": dict(strategy_family.scorecard or {}),
                "strategy_scorecard_buckets": dict((strategy_family.scorecard or {}).get("buckets", {})),
                "strategy_scorecard_raw_components": dict((strategy_family.scorecard or {}).get("raw_components", {})),
                "strategy_scorecard_trendline_bonus": float((strategy_family.scorecard or {}).get("buckets", {}).get("trendline_bonus", 0.0)),
                "strategy_family_clean_case": bool(strategy_family.clean_case),
                "strategy_family_confirm_only": bool(strategy_family.confirm_only),
                "strategy_family_time_stop_min_bars": int(strategy_family.time_stop_min_bars),
                "strategy_family_time_stop_max_bars": int(strategy_family.time_stop_max_bars),
                "strategy_mode": mode_policy.mode.value,
                "mode_shadow_only": bool(mode_policy.shadow_only),
                "mode_daily_trade_limit": int(mode_policy.max_daily_trades),
                "mode_total_risk_cap_r": float(mode_policy.max_total_risk_r),
                "mode_rejected_reason": mode_reason,
                "strategy_sizing": strategy_sizing,
                "recommended_risk_r": float(strategy_sizing.get("final_risk_r", 0.0)),
                "expected_win_prob": round(win_prob, 4),
                "expected_win_prob_base": round(base_win_prob, 4),
                "expected_win_prob_adjustment": round(win_prob_adjustment, 4),
                "expected_win_prob_components": win_prob_components,
                "expected_ev_r": round(ev, 4),
                "expected_tp1_prob": round(p1_est, 4),
                "expected_tp2_prob": round(p2_est, 4),
                "expected_tp3_prob": round(p3_est, 4),
                "expected_ev_at_recommended_size_r": round(expected_ev_at_recommended_size_r, 4),
                "expected_summary": expected_summary,
                "zone_type": zone.type,
                "near_lp": bool(near_lp),
                "confluence_score": round(confluence_score, 2),
                "confluence_components": confluence_components,
                "feature_weights_base": feature_weights_base,
                "feature_weights_active": feature_weights_active,
                "zone_type_multiplier_active": zone_type_multiplier_active,
                "feature_calibration_available": bool(
                    importance_calibration
                    and self.settings.feature_calibration_enabled
                    and self.settings.feature_calibration_apply_runtime
                    and importance_calibration.get("available")
                ),
                "feature_calibration_samples": int((importance_calibration or {}).get("matched_samples", 0)),
                "reliability_factor": round(reliability, 3),
                "rr_floor": rr_floor,
                "ev_floor": zone_profile.ev_floor,
                "meta_score": round(meta_score, 2),
                "meta_threshold": round(meta_threshold, 2),
                "meta_reason": meta_reason,
                "transition_score": round(context.transition_score, 2),
                "transition_state": context.transition_state,
                "transition_features": dict(context.transition_features or {}),
                "transition_unlock_candidate": bool(context.transition_unlock_candidate),
                "transition_lock_reason": context.transition_lock_reason,
                "reaction_classifier_available": bool(reaction.available),
                "reaction_classification": reaction.classification,
                "reaction_rejection_score": round(reaction.rejection_score, 2),
                "reaction_acceptance_score": round(reaction.acceptance_score, 2),
                "reaction_rejection_hard_count": int(reaction.rejection_hard_count),
                "reaction_acceptance_hard_count": int(reaction.acceptance_hard_count),
                "reaction_mixed_reasons": list(reaction.mixed_reasons),
                "reaction_input": dict(reaction.input),
                "thesis_fingerprint": thesis_fingerprint,
                "thesis_cluster_id": thesis_cluster_id,
                "thesis_cluster_size": 1,
                "thesis_primary_symbol": symbol,
                "thesis_rejected_reason": None,
                "zone_age_hours": round(self._zone_age_hours(zone, now=now), 2),
                "scalp_zone_hard_max_age_hours": self._safe_int(self.settings.scalp_zone_hard_max_age_hours, default=24),
                "session_guidance_state": session_state,
                "session_guidance_session_name": session_name,
                "session_guidance_summary": str(session_guidance.get("summary", "")),
                "session_score_bias": round(session_score_bias, 4),
                "session_probability_adjustment": round(session_probability_adjustment, 4),
                "plan_validity_minutes": validity_minutes,
                "transition_edge_variant_enabled": bool(self.settings.transition_edge_variant_enabled),
                "transition_edge_variant_shadow_only": bool(self.settings.transition_edge_variant_shadow_only),
                "transition_edge_variant_applied": bool(transition_edge_variant is not None and not transition_edge_variant_shadow),
                "transition_edge_variant_shadow_evaluated": bool(transition_edge_variant is not None),
            }
            if transition_edge_variant is not None:
                validity["transition_edge_variant"] = {
                    "variant": "exp_6_fvg_relaxed_plus_transition_override",
                    "rescue_reason": str(transition_edge_variant.get("rescue_reason") or ""),
                    "shadow_only": bool(transition_edge_variant_shadow),
                    "confluence_score": round(float(transition_edge_variant.get("confluence_score") or 0.0), 2),
                    "min_confluence": round(float(transition_edge_variant["profile"].min_confluence), 2),
                }
            if location_reference is not None:
                validity["location_reference"] = location_reference
            if session_liquidity_reference is not None:
                validity["session_liquidity_reference"] = session_liquidity_reference
            if reaction_evidence is not None:
                validity["reaction_evidence"] = reaction_evidence
            if runtime_signal_telemetry is not None:
                validity["runtime_signal_telemetry"] = runtime_signal_telemetry
            if runtime_signal_shadow_tilt is not None:
                validity["runtime_signal_shadow_tilt"] = runtime_signal_shadow_tilt
            validity.update(
                self._fast_failure_validity(
                    symbol=symbol,
                    strategy_family=str(strategy_family.family),
                    entry_model=decision.model,
                    session_name=session_name,
                )
            )

            plan = Plan(
                plan_id=f"plan_{zone.zone_id}_{decision.model.value.lower()}",
                zone_id=zone.zone_id,
                symbol=symbol,
                timeframe="5m",
                direction=direction.value,
                entry_model=decision.model.value,
                entry_price=entry,
                entry_condition="touch_then_confirm" if decision.model != EntryModel.LIMIT else "limit_on_touch",
                sl=sl,
                tp1=tp1,
                tp2=tp2,
                tp3=tp3,
                split=split,
                rr_min=rr_min,
                rr_base=rr_base,
                rr_opt=rr_opt,
                ev=ev,
                cost_est=cost_est,
                confidence=confidence,
                validity=validity,
                state=state,
                valid_from=now,
                valid_until=now + timedelta(minutes=validity_minutes),
                strategy_version=self.settings.strategy_version,
            )
            out.append(RankedPlan(plan=plan, final_rank_score=final_score, friction_penalty=friction_penalty))

        out.sort(key=lambda x: (x.final_rank_score, x.plan.ev, x.plan.rr_base), reverse=True)
        return self._dedupe_ranked(out, context.atr15)
