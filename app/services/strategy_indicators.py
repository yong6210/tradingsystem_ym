from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.models import Plan, Zone
from app.services.candidate_expectations import expectation_contract
from app.services.context_engine import ContextSnapshot
from app.services.operator_text import entry_condition_message, why_now_message


class StrategyIndicatorsService:
    _NO_CANDIDATE_MESSAGE = "No active candidate for this symbol."

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return bool(default)

    @staticmethod
    def _round(value: Any, digits: int = 4) -> float:
        try:
            return round(float(value), digits)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _operator_status(row: dict[str, Any] | None) -> str:
        if not row:
            return "none"
        if StrategyIndicatorsService._safe_bool(row.get("accepted")):
            return "accepted"
        if row.get("block_reason"):
            return "blocked"
        return str(row.get("operator_status") or "none")

    @classmethod
    def _trade_now_status(cls, row: dict[str, Any] | None) -> str:
        if not row:
            return "NO_CANDIDATE"
        if not cls._safe_bool(row.get("accepted")) or row.get("block_reason") or str(row.get("deployment_go_no_go") or "") == "NO_GO":
            return "NO_GO"
        if str(row.get("deployment_go_no_go") or "") == "MANUAL_REVIEW":
            return "MANUAL_REVIEW"
        return "GO"

    @classmethod
    def _build_operator_summary(cls, *, symbol: str, top_candidate: dict[str, Any] | None) -> dict[str, Any]:
        row = dict(top_candidate or {})
        deployment_message = str(row.get("deployment_message") or cls._NO_CANDIDATE_MESSAGE)
        block_reason_message = str(row.get("block_reason_message") or "").strip() or None
        why_allowed_or_blocked = block_reason_message or deployment_message or cls._NO_CANDIDATE_MESSAGE
        trade_now_status = cls._trade_now_status(row or None)
        default_go_no_go = "NO_GO" if trade_now_status in {"NO_CANDIDATE", "NO_GO"} else trade_now_status
        return {
            "trade_now_status": trade_now_status,
            "can_trade_now": trade_now_status == "GO",
            "active_family": row.get("strategy_family"),
            "family_reason": row.get("strategy_family_reason"),
            "why_now": row.get("why_now") or "",
            "why_allowed_or_blocked": why_allowed_or_blocked,
            "top_plan_id": row.get("plan_id"),
            "deployment_go_no_go": row.get("deployment_go_no_go") or default_go_no_go,
            "deployment_code": row.get("deployment_code") or "no_active_candidate",
            "deployment_message": deployment_message,
            "strategy_mode": row.get("strategy_mode"),
            "risk_reason": row.get("risk_reason") or "normal",
            "operating_lock": dict(row.get("operating_lock") or {}),
            "session_guidance": dict(row.get("session_guidance") or {}),
            "block_reason": row.get("block_reason"),
            "block_reason_message": block_reason_message,
            "thesis_cluster_id": row.get("thesis_cluster_id"),
            "thesis_primary_symbol": row.get("thesis_primary_symbol") or symbol,
            "authority_source": "scanner_runtime_portfolio_gate",
        }

    @staticmethod
    def _bias_label(context: ContextSnapshot) -> str:
        if context.transition_state == "transition_confirmed":
            return "mixed"
        if context.vz >= 0.8 and context.az >= 0.1:
            return "bullish_acceleration"
        if context.vz <= -0.8 and context.az <= -0.1:
            return "bearish_acceleration"
        if context.v > 0.15:
            return "bullish"
        if context.v < -0.15:
            return "bearish"
        return "neutral"

    @staticmethod
    def _risk_label(context: ContextSnapshot) -> str:
        if context.transition_state == "transition_confirmed":
            return "blocked"
        if context.transition_state == "transition_watch":
            return "guarded"
        if context.friction_5m >= 0.65 or context.jump_rate_5m >= 0.30:
            return "high"
        if context.friction_5m >= 0.40 or context.jump_rate_5m >= 0.18:
            return "guarded"
        return "normal"

    @staticmethod
    def _momentum_label(context: ContextSnapshot) -> str:
        if abs(context.vz) < 0.35 and abs(context.az) < 0.35:
            return "flat"
        if context.vz > 0 and context.az > 0:
            return "building_up"
        if context.vz < 0 and context.az < 0:
            return "building_down"
        if context.vz > 0 and context.az < 0:
            return "up_but_slowing"
        if context.vz < 0 and context.az > 0:
            return "down_but_slowing"
        return "mixed"

    @staticmethod
    def _distance_atr(price_a: float, price_b: float, atr: float) -> float:
        if atr <= 0:
            return 0.0
        return abs(price_a - price_b) / atr

    @staticmethod
    def _risk_color_token(risk_label: str) -> str:
        mapping = {
            "blocked": "red",
            "high": "orange",
            "guarded": "yellow",
            "normal": "green",
        }
        return mapping.get(risk_label, "gray")

    @staticmethod
    def _direction_shape(direction: str) -> str:
        return "triangleup" if str(direction).lower() == "long" else "triangledown"

    def _zone_row(self, *, zone: Zone, last_price: float, atr15: float) -> dict[str, Any]:
        return {
            "zone_id": zone.zone_id,
            "type": zone.type,
            "dir_bias": zone.dir_bias,
            "low": self._round(zone.low, 4),
            "high": self._round(zone.high, 4),
            "mid": self._round(zone.mid, 4),
            "width_atr": self._round(zone.width_atr, 4),
            "quality": self._round(zone.quality, 2),
            "base_strength": self._round(zone.base_strength, 2),
            "state": zone.state,
            "touch_count": int(zone.touch_count),
            "distance_atr": self._round(self._distance_atr(last_price, float(zone.mid), atr15), 4),
        }

    def _plan_row(
        self,
        *,
        plan: Plan,
        last_price: float,
        atr15: float,
        assessed_row: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validity = dict(plan.validity or {})
        runtime_signal_shadow_tilt = dict(
            validity.get("runtime_signal_shadow_tilt")
            or dict(validity.get("strategy_sizing") or {}).get("runtime_signal_shadow_tilt")
            or {}
        )
        recommended_risk_r = float(validity.get("recommended_risk_r", 0.0) or 0.0)
        expectations = expectation_contract(
            validity=validity,
            ev=float(plan.ev),
            recommended_risk_r=recommended_risk_r,
        )
        assessed = dict(assessed_row or {})
        strategy_family_reason = str(
            assessed.get("strategy_family_reason")
            or validity.get("strategy_family_reason")
            or ""
        ).strip()
        return {
            "plan_id": plan.plan_id,
            "direction": plan.direction,
            "entry_model": plan.entry_model,
            "state": plan.state,
            "strategy_family": str(validity.get("strategy_family", "legacy_zone_plan")),
            "strategy_grade": validity.get("strategy_grade"),
            "entry_condition": entry_condition_message(
                plan.entry_condition,
                fallback_entry_model=plan.entry_model,
            ),
            "strategy_family_reason": strategy_family_reason or None,
            "why_now": why_now_message(strategy_family_reason),
            "strategy_scorecard_buckets": dict(validity.get("strategy_scorecard_buckets") or {}),
            "strategy_scorecard_raw_components": dict(validity.get("strategy_scorecard_raw_components") or {}),
            "operator_status": self._operator_status(assessed_row),
            "block_reason": assessed.get("block_reason"),
            "block_reason_message": assessed.get("block_reason_message"),
            "entry_price": self._round(plan.entry_price, 4),
            "sl": self._round(plan.sl, 4),
            "tp1": self._round(plan.tp1, 4),
            "tp2": self._round(plan.tp2, 4),
            "tp3": self._round(plan.tp3, 4),
            "rr_base": self._round(plan.rr_base, 4),
            "rr_opt": self._round(plan.rr_opt, 4),
            "ev": self._round(plan.ev, 4),
            "confluence_score": self._round(validity.get("confluence_score", 0.0), 2),
            "recommended_risk_r": self._round(recommended_risk_r, 4),
            "runtime_signal_shadow_tilt": runtime_signal_shadow_tilt,
            "expected_win_prob": self._round(expectations["expected_win_prob"], 4),
            "expected_ev_r": self._round(expectations["expected_ev_r"], 4),
            "expected_tp1_prob": self._round(expectations["expected_tp1_prob"], 4),
            "expected_tp2_prob": self._round(expectations["expected_tp2_prob"], 4),
            "expected_tp3_prob": self._round(expectations["expected_tp3_prob"], 4),
            "expected_ev_at_recommended_size_r": self._round(expectations["expected_ev_at_recommended_size_r"], 4),
            "expected_summary": expectations["expected_summary"],
            "distance_to_entry_atr": self._round(self._distance_atr(last_price, float(plan.entry_price), atr15), 4),
        }

    def build_summary(
        self,
        *,
        symbol: str,
        context: ContextSnapshot | None,
        plans: list[Plan],
        zones: list[Zone],
        refresh: dict[str, Any],
        assessed_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc).isoformat()
        assessed_by_plan = {
            str(row.get("plan_id")): dict(row)
            for row in (assessed_rows or [])
            if row.get("plan_id")
        }
        operator_summary = self._build_operator_summary(
            symbol=symbol,
            top_candidate=(assessed_rows or [None])[0],
        )
        if context is None:
            return {
                "available": False,
                "reason": "insufficient_candles",
                "symbol": symbol,
                "generated_at": generated_at,
                "refresh": refresh,
                "headline": "",
                "readable_lines": [],
                "bias_label": "unknown",
                "momentum_label": "unknown",
                "risk_label": "unknown",
                "context": {},
                "operator_summary": operator_summary,
                "top_plan": None,
                "top_zones": [],
            }

        bias_label = self._bias_label(context)
        risk_label = self._risk_label(context)
        momentum_label = self._momentum_label(context)
        plan_rows = [
            self._plan_row(
                plan=plan,
                last_price=context.last_price,
                atr15=context.atr15,
                assessed_row=assessed_by_plan.get(plan.plan_id),
            )
            for plan in plans
        ]
        zone_rows = [
            self._zone_row(zone=zone, last_price=context.last_price, atr15=context.atr15)
            for zone in sorted(
                zones,
                key=lambda row: (
                    self._distance_atr(context.last_price, float(row.mid), context.atr15),
                    -float(row.quality),
                    -float(row.base_strength),
                ),
            )
        ]
        top_plan = plan_rows[0] if plan_rows else None
        headline = (
            f"{context.regime_label} | bias={bias_label} | risk={risk_label} | "
            f"transition={context.transition_state}"
        )
        readable_lines = [
            (
                f"시장상태: {context.regime_label}, transition={context.transition_state}, "
                f"jump={context.jump_rate_5m:.3f}, friction={context.friction_5m:.3f}"
            ),
            (
                f"모멘텀: {momentum_label}, v_z={context.vz:.2f}, a_z={context.az:.2f}, "
                f"sdir={context.sdir:.3f}, sevt={context.sevt:.3f}"
            ),
        ]
        if top_plan:
            readable_lines.append(
                (
                    f"최우선 플랜: {top_plan['direction']} {top_plan['entry_model']} | "
                    f"{top_plan['expected_summary']} | risk≈{top_plan['recommended_risk_r']:.3f}R"
                )
            )
            if top_plan.get("why_now"):
                readable_lines.append(
                    f"Why now: {top_plan['why_now']}"
                )
        if zone_rows:
            nearest_zone = zone_rows[0]
            readable_lines.append(
                (
                    f"가까운 존: {nearest_zone['type']} {nearest_zone['dir_bias']} | "
                    f"mid={nearest_zone['mid']:.4f}, dist≈{nearest_zone['distance_atr']:.2f} ATR"
                )
            )
        readable_lines.append(
            f"Operator: {operator_summary['trade_now_status']} | {operator_summary['why_allowed_or_blocked']}"
        )

        return {
            "available": True,
            "reason": "ok",
            "symbol": symbol,
            "generated_at": generated_at,
            "refresh": refresh,
            "headline": headline,
            "readable_lines": readable_lines,
            "bias_label": bias_label,
            "momentum_label": momentum_label,
            "risk_label": risk_label,
            "context": {
                "last_price": self._round(context.last_price, 4),
                "atr5": self._round(context.atr5, 4),
                "atr15": self._round(context.atr15, 4),
                "regime_label": context.regime_label,
                "regime_score": self._round(context.regime_15m, 4),
                "sdir": self._round(context.sdir, 4),
                "sevt": self._round(context.sevt, 4),
                "f": self._round(context.f, 4),
                "v": self._round(context.v, 4),
                "a": self._round(context.a, 4),
                "vz": self._round(context.vz, 4),
                "az": self._round(context.az, 4),
                "jump_rate_5m": self._round(context.jump_rate_5m, 4),
                "friction_5m": self._round(context.friction_5m, 4),
                "transition_score": self._round(context.transition_score, 4),
                "transition_state": context.transition_state,
                "transition_lock_reason": context.transition_lock_reason,
            },
            "operator_summary": operator_summary,
            "top_plan": top_plan,
            "top_zones": zone_rows,
        }

    def build_chart_payload(
        self,
        *,
        symbol: str,
        context: ContextSnapshot | None,
        plans: list[Plan],
        zones: list[Zone],
        refresh: dict[str, Any],
        assessed_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc).isoformat()
        assessed_by_plan = {
            str(row.get("plan_id")): dict(row)
            for row in (assessed_rows or [])
            if row.get("plan_id")
        }
        operator_summary = self._build_operator_summary(
            symbol=symbol,
            top_candidate=(assessed_rows or [None])[0],
        )
        if context is None:
            return {
                "available": False,
                "reason": "insufficient_candles",
                "symbol": symbol,
                "generated_at": generated_at,
                "refresh": refresh,
                "price_panel": {},
                "indicator_panel": {},
                "operator_summary": operator_summary,
                "zones": [],
                "plans": [],
                "annotations": [],
            }

        plan_rows = [
            self._plan_row(
                plan=plan,
                last_price=context.last_price,
                atr15=context.atr15,
                assessed_row=assessed_by_plan.get(plan.plan_id),
            )
            for plan in plans
        ]
        zone_rows = [
            self._zone_row(zone=zone, last_price=context.last_price, atr15=context.atr15)
            for zone in sorted(
                zones,
                key=lambda row: (
                    self._distance_atr(context.last_price, float(row.mid), context.atr15),
                    -float(row.quality),
                    -float(row.base_strength),
                ),
            )
        ]
        annotations = [
            f"bias={self._bias_label(context)}",
            f"momentum={self._momentum_label(context)}",
            f"risk={self._risk_label(context)}",
            f"transition={context.transition_state}",
        ]
        return {
            "available": True,
            "reason": "ok",
            "symbol": symbol,
            "generated_at": generated_at,
            "refresh": refresh,
            "price_panel": {
                "last_price": self._round(context.last_price, 4),
                "atr5": self._round(context.atr5, 4),
                "atr15": self._round(context.atr15, 4),
            },
            "indicator_panel": {
                "regime_label": context.regime_label,
                "regime_score": self._round(context.regime_15m, 4),
                "sdir": self._round(context.sdir, 4),
                "sevt": self._round(context.sevt, 4),
                "f": self._round(context.f, 4),
                "v": self._round(context.v, 4),
                "a": self._round(context.a, 4),
                "vz": self._round(context.vz, 4),
                "az": self._round(context.az, 4),
                "jump_rate_5m": self._round(context.jump_rate_5m, 4),
                "friction_5m": self._round(context.friction_5m, 4),
                "transition_score": self._round(context.transition_score, 4),
                "transition_state": context.transition_state,
                "transition_lock_reason": context.transition_lock_reason,
            },
            "operator_summary": operator_summary,
            "zones": zone_rows,
            "plans": plan_rows,
            "annotations": annotations,
        }

    def build_pine_payload(
        self,
        *,
        symbol: str,
        context: ContextSnapshot | None,
        plans: list[Plan],
        zones: list[Zone],
        refresh: dict[str, Any],
        assessed_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc).isoformat()
        assessed_by_plan = {
            str(row.get("plan_id")): dict(row)
            for row in (assessed_rows or [])
            if row.get("plan_id")
        }
        operator_summary = self._build_operator_summary(
            symbol=symbol,
            top_candidate=(assessed_rows or [None])[0],
        )
        if context is None:
            return {
                "available": False,
                "reason": "insufficient_candles",
                "symbol": symbol,
                "generated_at": generated_at,
                "refresh": refresh,
                "overlay": {},
                "panels": {},
                "operator_summary": operator_summary,
                "signals": [],
                "zones": [],
                "plans": [],
            }

        bias_label = self._bias_label(context)
        risk_label = self._risk_label(context)
        plan_rows = [
            self._plan_row(
                plan=plan,
                last_price=context.last_price,
                atr15=context.atr15,
                assessed_row=assessed_by_plan.get(plan.plan_id),
            )
            for plan in plans
        ]
        zone_rows = [
            self._zone_row(zone=zone, last_price=context.last_price, atr15=context.atr15)
            for zone in sorted(
                zones,
                key=lambda row: (
                    self._distance_atr(context.last_price, float(row.mid), context.atr15),
                    -float(row.quality),
                    -float(row.base_strength),
                ),
            )
        ]
        zone_boxes = [
            {
                "id": row["zone_id"],
                "kind": "box",
                "top": row["high"],
                "bottom": row["low"],
                "mid": row["mid"],
                "label": f"{row['type']} {row['dir_bias']}",
                "color_token": "support" if row["dir_bias"] == "support" else "resistance",
                "quality": row["quality"],
                "distance_atr": row["distance_atr"],
            }
            for row in zone_rows
        ]
        plot_lines = [
            {
                "id": "last_price",
                "kind": "plot",
                "style": "line",
                "label": "Last Price",
                "value": self._round(context.last_price, 4),
                "color_token": "price",
            },
            {
                "id": "atr15_upper",
                "kind": "plot",
                "style": "line",
                "label": "ATR15 Upper",
                "value": self._round(context.last_price + context.atr15, 4),
                "color_token": "atr_band",
            },
            {
                "id": "atr15_lower",
                "kind": "plot",
                "style": "line",
                "label": "ATR15 Lower",
                "value": self._round(context.last_price - context.atr15, 4),
                "color_token": "atr_band",
            },
        ]
        signals = []
        for row in plan_rows:
            signals.append(
                {
                    "id": row["plan_id"],
                    "kind": "shape",
                    "shape": self._direction_shape(row["direction"]),
                    "label": f"{row['direction']} {row['entry_model']}",
                    "price": row["entry_price"],
                    "color_token": "long" if row["direction"] == "long" else "short",
                    "expected_summary": row["expected_summary"],
                    "recommended_risk_r": row["recommended_risk_r"],
                    "why_now": row["why_now"],
                    "strategy_family": row["strategy_family"],
                    "operator_status": row["operator_status"],
                    "block_reason_message": row["block_reason_message"],
                }
            )
            plot_lines.extend(
                [
                    {
                        "id": f"{row['plan_id']}:entry",
                        "kind": "hline",
                        "label": f"{row['plan_id']} entry",
                        "value": row["entry_price"],
                        "color_token": "entry",
                    },
                    {
                        "id": f"{row['plan_id']}:sl",
                        "kind": "hline",
                        "label": f"{row['plan_id']} sl",
                        "value": row["sl"],
                        "color_token": "stop",
                    },
                    {
                        "id": f"{row['plan_id']}:tp1",
                        "kind": "hline",
                        "label": f"{row['plan_id']} tp1",
                        "value": row["tp1"],
                        "color_token": "target",
                    },
                    {
                        "id": f"{row['plan_id']}:tp2",
                        "kind": "hline",
                        "label": f"{row['plan_id']} tp2",
                        "value": row["tp2"],
                        "color_token": "target",
                    },
                    {
                        "id": f"{row['plan_id']}:tp3",
                        "kind": "hline",
                        "label": f"{row['plan_id']} tp3",
                        "value": row["tp3"],
                        "color_token": "target",
                    },
                ]
            )

        return {
            "available": True,
            "reason": "ok",
            "symbol": symbol,
            "generated_at": generated_at,
            "refresh": refresh,
            "overlay": {
                "bgcolor_token": f"{bias_label}:{risk_label}",
                "bgcolor_color_token": self._risk_color_token(risk_label),
                "bgcolor_opacity": 84,
                "plot_lines": plot_lines,
                "zone_boxes": zone_boxes,
            },
            "panels": {
                "momentum": {
                    "sdir": self._round(context.sdir, 4),
                    "sevt": self._round(context.sevt, 4),
                    "v": self._round(context.v, 4),
                    "a": self._round(context.a, 4),
                    "vz": self._round(context.vz, 4),
                    "az": self._round(context.az, 4),
                    "label": self._momentum_label(context),
                },
                "regime": {
                    "regime_label": context.regime_label,
                    "regime_score": self._round(context.regime_15m, 4),
                    "transition_state": context.transition_state,
                    "transition_score": self._round(context.transition_score, 4),
                },
                "risk": {
                    "risk_label": risk_label,
                    "jump_rate_5m": self._round(context.jump_rate_5m, 4),
                    "friction_5m": self._round(context.friction_5m, 4),
                    "transition_lock_reason": context.transition_lock_reason,
                },
            },
            "operator_summary": operator_summary,
            "signals": signals,
            "zones": zone_rows,
            "plans": plan_rows,
        }
