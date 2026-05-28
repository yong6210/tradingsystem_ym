from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

from app.core.enums import Direction
from app.db.models import Zone
from app.services.common import clamp
from app.services.context_engine import ContextSnapshot


@dataclass(slots=True)
class NanyottiMethodView:
    available: bool
    method_version: str
    source: str
    authority: str
    direction: str
    primary_bias: str
    bias_strength: float
    side_alignment: str
    rotation_role: str
    entry_quality: str
    method_score: float
    size_bias: str
    position_management_bias: str
    battle_permission: str
    switch_permission: str
    one_way_risk: str
    bad_rr_state: str
    repair_efficiency: float | None
    market_state: dict[str, Any]
    scenario_plan: dict[str, Any]
    inventory_state: dict[str, Any]
    repair_decision: dict[str, Any]
    execution_policy: dict[str, Any]
    switch_policy: dict[str, Any]
    sizing_overlay: dict[str, Any]
    diagnostics: dict[str, Any]
    reasons: list[str]
    no_trade_reasons: list[str]
    method_rules: list[str]


class NanyottiMethodViewService:
    """
    Shadow advisory layer distilled from the Telegram corpus analysis.

    This service does not create live order authority. It maps the sampled
    trading viewpoint into deterministic market-data diagnostics: trend rescue,
    location quality, one-way danger, bad RR/chase, repair capacity, and whether
    the idea should be probe/base/reduce-only.
    """

    METHOD_VERSION = "telegram_rotation_method_view_v1"

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
    def _value(value: Any) -> str:
        return str(getattr(value, "value", value) or "").strip().lower()

    @classmethod
    def _direction_value(cls, direction: Direction | str) -> str:
        value = cls._value(direction)
        if value in {"long", "short"}:
            return value
        return "long" if value == Direction.LONG.value else "short"

    @classmethod
    def _trend_proxy(cls, context: ContextSnapshot) -> float:
        return clamp(
            0.50 * cls._safe_float(context.v)
            + 0.30 * cls._safe_float(context.sdir)
            + 0.20 * cls._safe_float(context.f),
            -1.50,
            1.50,
        )

    @classmethod
    def _primary_bias(cls, trend_proxy: float, context: ContextSnapshot) -> tuple[str, float]:
        threshold = 0.28 if cls._value(context.regime_label) == "trend" else 0.35
        strength = clamp(abs(trend_proxy) / 1.10, 0.0, 1.0)
        if trend_proxy >= threshold:
            return "long", round(strength, 4)
        if trend_proxy <= -threshold:
            return "short", round(strength, 4)
        return "neutral", round(strength, 4)

    @staticmethod
    def _side_alignment(direction: str, primary_bias: str) -> str:
        if primary_bias == "neutral":
            return "neutral"
        if direction == primary_bias:
            return "with_trend"
        return "against_trend"

    @classmethod
    def _risk_atr(cls, *, entry_price: float, sl: float, context: ContextSnapshot, telemetry: dict[str, Any]) -> float:
        if "risk_atr" in telemetry:
            return max(cls._safe_float(telemetry.get("risk_atr")), 0.0)
        return abs(float(entry_price) - float(sl)) / max(cls._safe_float(context.atr15, 1e-9), 1e-9)

    @classmethod
    def _entry_offset_atr(
        cls,
        *,
        entry_price: float,
        context: ContextSnapshot,
        telemetry: dict[str, Any],
    ) -> float:
        if "entry_offset_atr" in telemetry:
            return max(cls._safe_float(telemetry.get("entry_offset_atr")), 0.0)
        return abs(float(entry_price) - cls._safe_float(context.last_price)) / max(cls._safe_float(context.atr15, 1e-9), 1e-9)

    @classmethod
    def _one_way_score(
        cls,
        *,
        context: ContextSnapshot,
        side_alignment: str,
        trend_proxy: float,
    ) -> float:
        if side_alignment != "against_trend":
            return clamp(10.0 + abs(trend_proxy) * 12.0 + cls._safe_float(context.regime_15m) * 10.0, 0.0, 45.0)

        return clamp(
            28.0
            + cls._safe_float(context.regime_15m) * 24.0
            + min(abs(trend_proxy), 1.20) / 1.20 * 24.0
            + min(abs(cls._safe_float(context.sdir)), 1.20) / 1.20 * 12.0
            + min(abs(cls._safe_float(context.vz)), 2.00) / 2.00 * 8.0
            + (8.0 if cls._value(context.regime_label) == "trend" else 0.0)
            + (6.0 if cls._safe_float(context.friction_5m) >= 0.45 else 0.0)
            + (6.0 if cls._safe_float(context.jump_rate_5m) >= 0.18 else 0.0),
            0.0,
            100.0,
        )

    @staticmethod
    def _risk_bucket(score: float) -> str:
        if score >= 70.0:
            return "high"
        if score >= 45.0:
            return "medium"
        return "low"

    @classmethod
    def _bad_rr_state(
        cls,
        *,
        zone: Zone,
        context: ContextSnapshot,
        risk_atr: float,
        entry_offset_atr: float,
        telemetry: dict[str, Any],
        location_reference: dict[str, Any],
    ) -> tuple[str, list[str], float]:
        reasons: list[str] = []
        score = 0.0
        width_atr = cls._safe_float(getattr(zone, "width_atr", 0.0))
        edge_proximity_atr = cls._safe_float(location_reference.get("edge_proximity_atr"), default=width_atr * 0.5)
        directional_fast_extension = cls._safe_float(telemetry.get("directional_close_vs_ema_fast_atr"))

        if risk_atr >= 1.15:
            score += 32.0
            reasons.append("wide_stop_risk")
        elif risk_atr >= 0.85:
            score += 16.0
            reasons.append("moderate_stop_risk")

        if width_atr >= 0.90 or edge_proximity_atr >= 0.45:
            score += 22.0
            reasons.append("wide_or_centered_zone")

        if entry_offset_atr >= 1.25:
            score += 24.0
            reasons.append("late_entry_offset")

        if directional_fast_extension >= 0.75:
            score += 18.0
            reasons.append("directional_chase_extension")

        if cls._safe_float(context.friction_5m) >= 0.45 or cls._safe_float(context.jump_rate_5m) >= 0.18:
            score += 18.0
            reasons.append("noisy_execution_cost")

        if score >= 55.0:
            return "bad_rr", reasons, round(clamp(score, 0.0, 100.0), 2)
        if score >= 28.0:
            return "watch", reasons, round(score, 2)
        return "acceptable", reasons, round(score, 2)

    @classmethod
    def _expected_reaction_atr(
        cls,
        *,
        bad_rr_score: float,
        one_way_score: float,
        reaction_classification: str,
        side_alignment: str,
    ) -> float:
        expected_reaction_atr = 0.70
        if side_alignment == "with_trend":
            expected_reaction_atr += 0.25
        if reaction_classification == "rejection_confirmed":
            expected_reaction_atr += 0.25
        elif reaction_classification == "rejection_tentative":
            expected_reaction_atr += 0.12
        expected_reaction_atr -= min(bad_rr_score / 100.0 * 0.25, 0.25)
        expected_reaction_atr -= min(one_way_score / 100.0 * 0.20, 0.20)
        return round(max(expected_reaction_atr, 0.25), 4)

    @classmethod
    def _repair_efficiency(
        cls,
        *,
        risk_atr: float,
        bad_rr_score: float,
        one_way_score: float,
        reaction_classification: str,
        side_alignment: str,
    ) -> float:
        expected_reaction_atr = cls._expected_reaction_atr(
            bad_rr_score=bad_rr_score,
            one_way_score=one_way_score,
            reaction_classification=reaction_classification,
            side_alignment=side_alignment,
        )
        return round(risk_atr / max(expected_reaction_atr, 0.25), 4)

    @classmethod
    def _rotation_role(
        cls,
        *,
        strategy_family: str,
        reaction_classification: str,
        regime_label: str,
        side_alignment: str,
        one_way_risk: str,
        bad_rr_state: str,
    ) -> str:
        family = str(strategy_family or "").strip().lower()
        reaction = str(reaction_classification or "").strip().lower()
        if one_way_risk == "high" and side_alignment == "against_trend":
            return "one_way_risk"
        if bad_rr_state == "bad_rr":
            return "bad_rr_watch"
        if family == "trend_continuation" or (regime_label == "trend" and side_alignment == "with_trend"):
            return "trend_pullback"
        if family == "sweep_reversal" or reaction.startswith("rejection_"):
            return "sweep_reversal"
        if regime_label == "range":
            return "range_edge_rotation"
        return "structure_rotation"

    @classmethod
    def _repair_action(cls, repair_efficiency: float) -> str:
        if repair_efficiency <= 0.60:
            return "repairable_hold_or_reduce_battle_on_reaction"
        if repair_efficiency <= 1.10:
            return "thin_margin_reduce_battle_first"
        if repair_efficiency <= 1.50:
            return "do_not_add_rotate_loss_or_wait"
        return "trapped_average_reduce_only"

    @staticmethod
    def _entry_stage(
        *,
        entry_quality: str,
        position_management_bias: str,
        battle_permission: str,
        bad_rr_state: str,
        touch_count: int,
        zone_quality: float,
    ) -> str:
        if zone_quality < 45.0 or touch_count >= 4:
            return "retired"
        if entry_quality == "NO_TRADE" or bad_rr_state == "bad_rr":
            return "watch"
        if battle_permission == "battle_candidate":
            return "battle_candidate"
        if position_management_bias == "base_allowed":
            return "base"
        return "probe"

    @staticmethod
    def _max_risk_multiplier(
        *,
        entry_quality: str,
        size_bias: str,
        side_alignment: str,
        one_way_risk: str,
        bad_rr_state: str,
        repair_efficiency: float,
    ) -> float:
        if entry_quality == "NO_TRADE":
            return 0.0
        if size_bias == "normal":
            multiplier = 1.0
        elif size_bias == "probe":
            multiplier = 0.50
        elif size_bias == "reduced":
            multiplier = 0.25
        else:
            multiplier = 0.0

        if side_alignment == "against_trend":
            multiplier = min(multiplier, 0.35)
        if one_way_risk == "high" and side_alignment == "against_trend":
            multiplier = 0.0
        if bad_rr_state == "watch":
            multiplier = min(multiplier, 0.35)
        if bad_rr_state == "bad_rr":
            multiplier = 0.0
        if repair_efficiency > 1.10:
            multiplier = min(multiplier, 0.25)
        if repair_efficiency > 1.50:
            multiplier = 0.0
        return round(clamp(multiplier, 0.0, 1.0), 4)

    @staticmethod
    def _switch_blockers(
        *,
        switch_permission: str,
        side_alignment: str,
        one_way_risk: str,
        bad_rr_state: str,
        entry_quality: str,
        repair_efficiency: float,
    ) -> list[str]:
        blockers: list[str] = []
        if switch_permission == "forbidden_until_bias_fails":
            blockers.append("primary_bias_not_failed")
        if side_alignment == "against_trend" and one_way_risk == "high":
            blockers.append("one_way_opposite_switch_forbidden")
        if bad_rr_state == "bad_rr":
            blockers.append("opposite_side_bad_rr")
        if entry_quality == "NO_TRADE":
            blockers.append("candidate_no_trade")
        if repair_efficiency > 1.10:
            blockers.append("recovery_math_not_favorable")
        return sorted(set(blockers))

    @classmethod
    def build_sizing_overlay(
        cls,
        *,
        method_view: dict[str, Any],
        base_recommended_risk_r: float,
        expected_ev_r: float,
        apply_live: bool = False,
    ) -> dict[str, Any]:
        execution_policy = dict(method_view.get("execution_policy") or {})
        multiplier = cls._safe_float(execution_policy.get("max_risk_multiplier"), default=1.0)
        multiplier = clamp(multiplier, 0.0, 1.0)
        base_risk = max(cls._safe_float(base_recommended_risk_r), 0.0)
        shadow_risk = round(base_risk * multiplier, 4)
        live_risk = shadow_risk if apply_live else base_risk
        base_ev_at_size = round(base_risk * cls._safe_float(expected_ev_r), 4)
        shadow_ev_at_size = round(shadow_risk * cls._safe_float(expected_ev_r), 4)
        return {
            "policy": "nanyotti_rotation_method_sizing_overlay_v1",
            "apply_live": bool(apply_live),
            "authority": "live_risk_modifier" if apply_live else "shadow_advisory_only",
            "base_recommended_risk_r": round(base_risk, 4),
            "shadow_recommended_risk_r": shadow_risk,
            "live_recommended_risk_r": round(live_risk, 4),
            "max_risk_multiplier": round(multiplier, 4),
            "shadow_blocked": bool(shadow_risk <= 0.0 and base_risk > 0.0),
            "base_expected_ev_at_size_r": base_ev_at_size,
            "shadow_expected_ev_at_size_r": shadow_ev_at_size,
            "delta_expected_ev_at_size_r": round(shadow_ev_at_size - base_ev_at_size, 4),
            "entry_quality": str(method_view.get("entry_quality") or ""),
            "size_bias": str(method_view.get("size_bias") or ""),
            "position_management_bias": str(method_view.get("position_management_bias") or ""),
            "reason_codes": list(method_view.get("no_trade_reasons") or method_view.get("reasons") or []),
        }

    @classmethod
    def evaluate(
        cls,
        *,
        context: ContextSnapshot,
        zone: Zone,
        direction: Direction | str,
        entry_price: float,
        sl: float,
        strategy_family: str,
        strategy_grade: str | None = None,
        reaction_classification: str = "not_applicable",
        runtime_signal_telemetry: dict[str, Any] | None = None,
        location_reference: dict[str, Any] | None = None,
        regime_label: str | None = None,
    ) -> dict[str, Any]:
        direction_value = cls._direction_value(direction)
        telemetry = dict(runtime_signal_telemetry or {})
        location = dict(location_reference or {})
        resolved_regime = str(regime_label or context.regime_label or "range").strip().lower()
        reaction = str(reaction_classification or "not_applicable").strip().lower()
        family = str(strategy_family or "legacy_zone_plan").strip().lower()
        grade = str(strategy_grade or "").strip().upper()

        trend_proxy = cls._trend_proxy(context)
        primary_bias, bias_strength = cls._primary_bias(trend_proxy, context)
        side_alignment = cls._side_alignment(direction_value, primary_bias)
        risk_atr = cls._risk_atr(entry_price=entry_price, sl=sl, context=context, telemetry=telemetry)
        entry_offset_atr = cls._entry_offset_atr(entry_price=entry_price, context=context, telemetry=telemetry)
        one_way_score = cls._one_way_score(context=context, side_alignment=side_alignment, trend_proxy=trend_proxy)
        one_way_risk = cls._risk_bucket(one_way_score)
        bad_rr_state, bad_rr_reasons, bad_rr_score = cls._bad_rr_state(
            zone=zone,
            context=context,
            risk_atr=risk_atr,
            entry_offset_atr=entry_offset_atr,
            telemetry=telemetry,
            location_reference=location,
        )
        repair_efficiency = cls._repair_efficiency(
            risk_atr=risk_atr,
            bad_rr_score=bad_rr_score,
            one_way_score=one_way_score,
            reaction_classification=reaction,
            side_alignment=side_alignment,
        )
        expected_reaction_atr = cls._expected_reaction_atr(
            bad_rr_score=bad_rr_score,
            one_way_score=one_way_score,
            reaction_classification=reaction,
            side_alignment=side_alignment,
        )

        reasons: list[str] = []
        no_trade_reasons: list[str] = []
        if primary_bias != "neutral":
            reasons.append(f"primary_bias_{primary_bias}")
        if side_alignment == "with_trend":
            reasons.append("market_rescues_same_side")
        elif side_alignment == "against_trend":
            reasons.append("against_primary_trend")
        if reaction.startswith("rejection_"):
            reasons.append(reaction)
        if family:
            reasons.append(f"family_{family}")
        reasons.extend(bad_rr_reasons)

        if resolved_regime in {"shock", "transition"} or str(context.transition_state or "") == "transition_watch":
            no_trade_reasons.append("unstable_transition_or_shock")
        if one_way_risk == "high" and side_alignment == "against_trend":
            no_trade_reasons.append("one_way_against_trade")
        if bad_rr_state == "bad_rr":
            no_trade_reasons.append("bad_rr_or_chase")
        if repair_efficiency >= 1.35:
            no_trade_reasons.append("poor_repair_efficiency")
        if cls._safe_float(getattr(zone, "quality", 0.0)) < 45.0 or cls._safe_float(getattr(zone, "base_strength", 0.0)) < 45.0:
            no_trade_reasons.append("weak_zone")

        score = 52.0
        score += 16.0 if side_alignment == "with_trend" else 4.0 if side_alignment == "neutral" else -18.0
        score += {"A": 12.0, "B": 5.0, "C": -5.0, "F": -16.0}.get(grade, 0.0)
        score += 14.0 if reaction == "rejection_confirmed" else 7.0 if reaction == "rejection_tentative" else 0.0
        score += clamp((cls._safe_float(getattr(zone, "quality", 50.0)) - 55.0) * 0.20, -8.0, 8.0)
        score += 4.0 if family == "trend_continuation" and side_alignment == "with_trend" else 0.0
        score -= bad_rr_score * 0.38
        score -= one_way_score * (0.38 if side_alignment == "against_trend" else 0.12)
        if resolved_regime in {"shock", "transition"}:
            score -= 12.0
        if str(context.transition_state or "") == "transition_watch":
            score -= 10.0
        score = round(clamp(score, 0.0, 100.0), 2)

        if no_trade_reasons or score < 38.0:
            entry_quality = "NO_TRADE"
        elif score >= 78.0:
            entry_quality = "A"
        elif score >= 60.0:
            entry_quality = "B"
        else:
            entry_quality = "C"

        if entry_quality == "NO_TRADE":
            size_bias = "observe"
            position_management_bias = "reduce_only"
        elif entry_quality == "A" and side_alignment == "with_trend":
            size_bias = "normal"
            position_management_bias = "base_allowed"
        elif entry_quality in {"A", "B"}:
            size_bias = "probe"
            position_management_bias = "probe_only"
        else:
            size_bias = "reduced"
            position_management_bias = "probe_only"

        if (
            entry_quality in {"A", "B"}
            and one_way_risk != "high"
            and bad_rr_state != "bad_rr"
            and repair_efficiency <= 1.05
            and side_alignment in {"with_trend", "neutral"}
        ):
            battle_permission = "battle_candidate"
        else:
            battle_permission = "battle_forbidden"

        if one_way_risk == "high" and side_alignment == "against_trend":
            switch_permission = "forbidden_until_bias_fails"
        elif reaction.startswith("rejection_") and side_alignment != "against_trend":
            switch_permission = "allowed_after_failed_acceptance"
        else:
            switch_permission = "not_automatic_requires_new_structure"

        max_risk_multiplier = cls._max_risk_multiplier(
            entry_quality=entry_quality,
            size_bias=size_bias,
            side_alignment=side_alignment,
            one_way_risk=one_way_risk,
            bad_rr_state=bad_rr_state,
            repair_efficiency=repair_efficiency,
        )
        rotation_role = cls._rotation_role(
            strategy_family=family,
            reaction_classification=reaction,
            regime_label=resolved_regime,
            side_alignment=side_alignment,
            one_way_risk=one_way_risk,
            bad_rr_state=bad_rr_state,
        )
        touch_count = int(cls._safe_float(getattr(zone, "touch_count", 0), default=0.0))
        zone_quality = cls._safe_float(getattr(zone, "quality", 0.0))
        scenario_stage = cls._entry_stage(
            entry_quality=entry_quality,
            position_management_bias=position_management_bias,
            battle_permission=battle_permission,
            bad_rr_state=bad_rr_state,
            touch_count=touch_count,
            zone_quality=zone_quality,
        )
        switch_blockers = cls._switch_blockers(
            switch_permission=switch_permission,
            side_alignment=side_alignment,
            one_way_risk=one_way_risk,
            bad_rr_state=bad_rr_state,
            entry_quality=entry_quality,
            repair_efficiency=repair_efficiency,
        )
        repair_action = cls._repair_action(repair_efficiency)

        view = NanyottiMethodView(
            available=True,
            method_version=cls.METHOD_VERSION,
            source="telegram_messages_as_pattern_sample_not_signal",
            authority="shadow_advisory_only",
            direction=direction_value,
            primary_bias=primary_bias,
            bias_strength=bias_strength,
            side_alignment=side_alignment,
            rotation_role=rotation_role,
            entry_quality=entry_quality,
            method_score=score,
            size_bias=size_bias,
            position_management_bias=position_management_bias,
            battle_permission=battle_permission,
            switch_permission=switch_permission,
            one_way_risk=one_way_risk,
            bad_rr_state=bad_rr_state,
            repair_efficiency=repair_efficiency,
            market_state={
                "primary_bias": primary_bias,
                "bias_strength": bias_strength,
                "trend_proxy": round(trend_proxy, 4),
                "regime": resolved_regime,
                "transition_state": str(context.transition_state or "none"),
                "side_alignment": side_alignment,
                "one_way_score": round(one_way_score, 2),
                "one_way_risk": one_way_risk,
            },
            scenario_plan={
                "side": direction_value,
                "zone_role": str(getattr(zone, "dir_bias", "") or "").lower(),
                "zone_type": str(getattr(zone, "type", "") or "").upper(),
                "stage": scenario_stage,
                "already_touched": bool(touch_count > 0),
                "touch_count": touch_count,
                "first_touch_reusable": bool(touch_count <= 1 and scenario_stage not in {"watch", "retired"}),
                "invalidation_price": round(float(sl), 4),
                "confidence": round(score / 100.0, 4),
                "lifecycle": "retired" if scenario_stage == "retired" else "watch" if scenario_stage == "watch" else "active",
            },
            inventory_state={
                "available": False,
                "reason": "position_inventory_not_attached_to_plan_generation",
                "proxy_used": "plan_risk_distance_as_recovery_distance",
                "remaining_capacity_state": "unknown",
                "leverage_rule": "10x_is_not_edge_without_remaining_capacity_and_reduction_rules",
            },
            repair_decision={
                "expected_reaction_atr": expected_reaction_atr,
                "recovery_distance_atr": round(risk_atr, 4),
                "repair_efficiency": repair_efficiency,
                "repair_action": repair_action,
                "reduce_battle_first": bool(repair_efficiency > 0.60 or bad_rr_state != "acceptable"),
                "new_add_allowed": bool(battle_permission == "battle_candidate"),
            },
            execution_policy={
                "allow_entry": bool(entry_quality != "NO_TRADE"),
                "entry_quality": entry_quality,
                "size_bias": size_bias,
                "position_management_bias": position_management_bias,
                "max_risk_multiplier": max_risk_multiplier,
                "battle_permission": battle_permission,
                "bad_rr_state": bad_rr_state,
                "risk_lane": "blocked" if max_risk_multiplier <= 0.0 else "normal" if max_risk_multiplier >= 0.75 else "probe",
            },
            switch_policy={
                "switch_permission": switch_permission,
                "switch_blockers": switch_blockers,
                "requires_new_structure": bool(switch_permission != "allowed_after_failed_acceptance"),
                "automatic_reverse_after_exit": False,
            },
            sizing_overlay={
                "policy": "nanyotti_rotation_method_sizing_overlay_v1",
                "enabled": True,
                "apply_live": False,
                "authority": "shadow_advisory_only",
                "max_risk_multiplier": max_risk_multiplier,
            },
            diagnostics={
                "regime": resolved_regime,
                "trend_proxy": round(trend_proxy, 4),
                "one_way_score": round(one_way_score, 2),
                "bad_rr_score": bad_rr_score,
                "risk_atr": round(risk_atr, 4),
                "entry_offset_atr": round(entry_offset_atr, 4),
                "zone_width_atr": round(cls._safe_float(getattr(zone, "width_atr", 0.0)), 4),
                "friction_5m": round(cls._safe_float(context.friction_5m), 4),
                "jump_rate_5m": round(cls._safe_float(context.jump_rate_5m), 4),
            },
            reasons=sorted(set(reasons)),
            no_trade_reasons=sorted(set(no_trade_reasons)),
            method_rules=[
                "messages_are_training_samples_not_live_signals",
                "switch_side_is_not_automatic_after_exit",
                "battle_add_requires_location_reaction_and_repair_capacity",
                "one_way_market_blocks_countertrend_averaging",
                "bad_rr_or_late_chase_defaults_to_probe_or_no_trade",
            ],
        )
        return asdict(view)
