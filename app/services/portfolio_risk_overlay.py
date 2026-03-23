from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import fmean, pstdev
from typing import Any

from app.core.config import Settings, get_settings
from app.db.models import Plan
from app.services.candidate_expectations import block_reason_message
from app.services.common import clamp
from app.services.position_sizing import PositionSizingService
from app.services.session_guidance import SessionGuidanceService
from app.services.strategy_mode import StrategyModeService
from app.services.thesis_fingerprint import ThesisFingerprintService


@dataclass(slots=True)
class _Exposure:
    symbol: str
    direction: str
    thesis_fingerprint: dict[str, str] | None = None
    priority: tuple[float, float, float, float] = (999999.0, 0.0, 999999.0, 0.0)


@dataclass(slots=True)
class _BudgetCaps:
    total: int
    directional: int
    cluster: int


@dataclass(slots=True)
class _ThesisCluster:
    cluster_id: str
    primary_symbol: str
    primary_priority: tuple[float, float, float, float]
    fingerprints: list[dict[str, str]] = field(default_factory=list)
    members: list[str] = field(default_factory=list)


class PortfolioRiskOverlayService:
    """Apply portfolio-level exposure limits to ranked scanner candidates."""

    _OUTCOME_BIAS_MIN_CLOSED = 4
    _OUTCOME_BIAS_POSITIVE_RATE = 0.5
    _OUTCOME_BIAS_NEGATIVE_RATE = 0.3
    _CAPITAL_ALLOCATOR_USABLE_MIN_CLOSED = 4
    _CAPITAL_ALLOCATOR_MATURE_MIN_CLOSED = 10
    _CAPITAL_ALLOCATOR_POSITIVE_RATE = 0.5
    _CAPITAL_ALLOCATOR_NEGATIVE_RATE = 0.3

    def __init__(self, candle_repo: Any | None = None, settings: Settings | None = None):
        self.candle_repo = candle_repo
        self.settings = settings or get_settings()
        self.thesis = ThesisFingerprintService()
        self.sizing = PositionSizingService(self.settings)
        self.mode = StrategyModeService(self.settings)
        self.session_guidance = SessionGuidanceService(self.settings)
        self._corr_cache: dict[tuple[str, str], float | None] = {}
        self._returns_cache: dict[str, dict[datetime, float]] = {}
        self._vol_cache: dict[str, float] = {}

    def _reset_cache(self) -> None:
        self._corr_cache.clear()
        self._returns_cache.clear()
        self._vol_cache.clear()

    def budget_caps_for_regime(self, regime: str) -> dict[str, int]:
        caps = self._budget_caps(regime)
        return {
            "total": int(caps.total),
            "directional": int(caps.directional),
            "cluster": int(caps.cluster),
        }

    def thesis_cluster_summary(
        self,
        existing_exposures: list[tuple[str, str] | dict[str, Any] | Plan] | None = None,
    ) -> list[dict[str, Any]]:
        exposures = self._normalize_exposures(existing_exposures)
        clusters = self._build_thesis_clusters(exposures)
        return [
            {
                "thesis_cluster_id": cluster.cluster_id,
                "thesis_primary_symbol": cluster.primary_symbol,
                "thesis_cluster_size": len(cluster.members),
                "members": list(cluster.members),
            }
            for cluster in clusters
        ]

    def exposure_metrics(
        self,
        existing_exposures: list[tuple[str, str] | dict[str, Any] | Plan] | None = None,
    ) -> list[dict[str, Any]]:
        self._reset_cache()
        exposures = self._normalize_exposures(existing_exposures)
        thesis_clusters = self._build_thesis_clusters(exposures)
        rows: list[dict[str, Any]] = []
        for exposure in exposures:
            same_direction = [item.symbol for item in exposures if item.direction == exposure.direction and item.symbol != exposure.symbol]
            high_corr_count = 0
            for other in same_direction:
                corr = self._correlation(exposure.symbol, other)
                if corr is not None and corr >= self.settings.portfolio_overlay_high_corr_threshold:
                    high_corr_count += 1
            thesis_cluster_id = None
            thesis_primary_symbol = None
            thesis_cluster_size = 1
            if exposure.thesis_fingerprint:
                matched_cluster = self._matching_cluster(thesis_clusters, exposure.thesis_fingerprint)
                thesis_cluster_id = matched_cluster.cluster_id if matched_cluster else self.thesis.thesis_cluster_id(exposure.thesis_fingerprint)
                thesis_primary_symbol = matched_cluster.primary_symbol if matched_cluster else exposure.symbol
                thesis_cluster_size = len(matched_cluster.members) if matched_cluster else 1
            rows.append(
                {
                    "symbol": exposure.symbol,
                    "direction": exposure.direction,
                    "portfolio_volatility": round(self._volatility(exposure.symbol), 6),
                    "portfolio_high_corr_count": int(high_corr_count),
                    "thesis_cluster_id": thesis_cluster_id,
                    "thesis_primary_symbol": thesis_primary_symbol,
                    "thesis_cluster_size": thesis_cluster_size,
                    "thesis_fingerprint": exposure.thesis_fingerprint,
                }
            )
        return rows

    def _normalize_exposures(
        self,
        existing_exposures: list[tuple[str, str] | dict[str, Any] | Plan] | None,
    ) -> list[_Exposure]:
        exposures: list[_Exposure] = []
        for item in existing_exposures or []:
            if isinstance(item, Plan):
                symbol = str(item.symbol or "").upper()
                direction = str(item.direction or "").lower()
                if not symbol or direction not in {"long", "short"}:
                    continue
                exposures.append(
                    _Exposure(
                        symbol=symbol,
                        direction=direction,
                        thesis_fingerprint=self.thesis.build_from_plan(item),
                        priority=self._priority_signature(item),
                    )
                )
                continue

            if isinstance(item, dict):
                symbol = str(item.get("symbol", "")).upper()
                direction = str(item.get("direction", "")).lower()
                if not symbol or direction not in {"long", "short"}:
                    continue
                exposures.append(
                    _Exposure(
                        symbol=symbol,
                        direction=direction,
                        thesis_fingerprint=self.thesis.build_from_candidate(item),
                        priority=self._priority_signature(item),
                    )
                )
                continue

            if isinstance(item, tuple) and len(item) >= 2:
                symbol = str(item[0] or "").upper()
                direction = str(item[1] or "").lower()
                if symbol and direction in {"long", "short"}:
                    exposures.append(_Exposure(symbol=symbol, direction=direction))

        return exposures

    @staticmethod
    def _priority_signature(item: Plan | dict[str, Any]) -> tuple[float, float, float, float]:
        if isinstance(item, Plan):
            invalidation = abs(float(item.entry_price) - float(item.sl))
            return (
                round(invalidation, 6),
                round(-float(item.ev), 6),
                round(float(item.cost_est), 6),
                round(-float(item.confidence), 6),
            )

        entry = float(item.get("entry_price", 0.0) or 0.0)
        sl = float(item.get("sl", entry) or entry)
        invalidation = abs(entry - sl) if entry > 0.0 else 999999.0
        return (
            round(invalidation, 6),
            round(-float(item.get("ev", 0.0) or 0.0), 6),
            round(float(item.get("cost_est", 0.0) or 0.0), 6),
            round(-float(item.get("confidence", item.get("final_rank_score", 0.0)) or 0.0), 6),
        )

    def _build_thesis_clusters(self, exposures: list[_Exposure]) -> list[_ThesisCluster]:
        clusters: list[_ThesisCluster] = []
        if not self.settings.thesis_dedupe_enabled:
            return clusters
        for exposure in exposures:
            if not exposure.thesis_fingerprint:
                continue
            cluster = self._matching_cluster(clusters, exposure.thesis_fingerprint)
            if cluster is None:
                clusters.append(
                    _ThesisCluster(
                        cluster_id=self.thesis.thesis_cluster_id(exposure.thesis_fingerprint),
                        primary_symbol=exposure.symbol,
                        primary_priority=exposure.priority,
                        fingerprints=[exposure.thesis_fingerprint],
                        members=[exposure.symbol],
                    )
                )
                continue
            cluster.fingerprints.append(exposure.thesis_fingerprint)
            if exposure.symbol not in cluster.members:
                cluster.members.append(exposure.symbol)
            if exposure.priority < cluster.primary_priority:
                cluster.primary_priority = exposure.priority
                cluster.primary_symbol = exposure.symbol
        return clusters

    def _matching_cluster(
        self,
        clusters: list[_ThesisCluster],
        fingerprint: dict[str, str] | None,
    ) -> _ThesisCluster | None:
        if not fingerprint:
            return None
        for cluster in clusters:
            if any(self.thesis.same_thesis(existing, fingerprint) for existing in cluster.fingerprints):
                return cluster
        return None

    def _attach_thesis_fields(
        self,
        *,
        row: dict[str, Any],
        fingerprint: dict[str, str] | None,
        cluster: _ThesisCluster | None = None,
        rejected_reason: str | None = None,
    ) -> None:
        row["thesis_fingerprint"] = fingerprint
        row["thesis_cluster_id"] = cluster.cluster_id if cluster else (self.thesis.thesis_cluster_id(fingerprint) if fingerprint else None)
        row["thesis_cluster_size"] = len(cluster.members) if cluster else 1
        row["thesis_primary_symbol"] = cluster.primary_symbol if cluster else row.get("symbol")
        row["thesis_rejected_reason"] = rejected_reason
        row["thesis_active_cluster_count"] = int(row.get("thesis_active_cluster_count", 0) or 0)

    @staticmethod
    def _risk_from_exposure(item: tuple[str, str] | dict[str, Any] | Plan) -> float:
        if isinstance(item, Plan):
            return float(dict(item.validity or {}).get("recommended_risk_r", 0.0) or 0.0)
        if isinstance(item, dict):
            validity = dict(item.get("validity") or {})
            return float(validity.get("recommended_risk_r", item.get("recommended_risk_r", 0.0)) or 0.0)
        return 0.0

    def _reset_alpha_research_fields(self, row: dict[str, Any]) -> None:
        row["alpha_research_candidate"] = False
        row["alpha_research_reason"] = None
        row["alpha_research_reason_message"] = None
        row["alpha_research_softened_risk_r"] = 0.0
        row["alpha_research_gap"] = 0.0

    def _maybe_route_to_alpha_research(
        self,
        *,
        row: dict[str, Any],
        reason: str,
    ) -> bool:
        if not self.settings.alpha_research_pipeline_enabled or not self.settings.quality_gate_softening_enabled:
            return False

        recommended_risk_r = float(row.get("recommended_risk_r", 0.0) or 0.0)
        expected_ev_r = float(row.get("expected_ev_r", 0.0) or 0.0)
        if recommended_risk_r <= 0.0 or expected_ev_r < float(self.settings.quality_gate_softening_min_expected_ev_r):
            return False

        gap = None
        if reason == "risk_budget_below_min":
            threshold = float(self.settings.portfolio_overlay_min_risk_budget_score)
            gap = max(0.0, threshold - float(row.get("risk_budget_score", 0.0) or 0.0))
            if gap > float(self.settings.quality_gate_softening_max_risk_budget_gap):
                return False
        elif reason == "adjusted_score_non_positive":
            gap = max(0.0, 0.0 - float(row.get("adjusted_rank_score", 0.0) or 0.0))
            if gap > float(self.settings.quality_gate_softening_max_adjusted_score_gap):
                return False
        else:
            return False

        row["alpha_research_candidate"] = True
        row["alpha_research_reason"] = reason
        row["alpha_research_reason_message"] = (
            "Quality gate near-miss routed to alpha research for shadow review instead of being dropped from follow-up."
        )
        row["alpha_research_softened_risk_r"] = round(
            max(0.0, recommended_risk_r * float(self.settings.alpha_research_softened_risk_scale)),
            4,
        )
        row["alpha_research_gap"] = round(float(gap or 0.0), 4)
        return True

    @staticmethod
    def _find_family_outcome_row(payload: dict[str, Any] | None, family: str) -> dict[str, Any]:
        rows = list(dict(payload or {}).get("families") or [])
        target = str(family or "")
        for row in rows:
            if str(row.get("family") or "") == target:
                return dict(row)
        return {}

    @staticmethod
    def _find_mode_bucket(payload: dict[str, Any] | None, *, axis: str, bucket: str) -> dict[str, Any]:
        rows = list(dict(payload or {}).get(axis, []) or [])
        target = str(bucket or "")
        for row in rows:
            if str(row.get("bucket") or "") == target:
                return dict(row)
        return {}

    @staticmethod
    def _find_funnel_bucket(payload: dict[str, Any] | None, *, axis: str, bucket: str) -> dict[str, Any]:
        rows = list(dict(payload or {}).get("decomposition", {}).get(axis, []) or [])
        target = str(bucket or "")
        for row in rows:
            if str(row.get("key") or "") == target:
                return dict(row)
        return {}

    @classmethod
    def _funnel_row_mature(cls, row: dict[str, Any]) -> bool:
        if not row:
            return False
        return int(row.get("closed", 0) or 0) >= cls._OUTCOME_BIAS_MIN_CLOSED

    @classmethod
    def _funnel_row_positive(cls, row: dict[str, Any]) -> bool:
        if not cls._funnel_row_mature(row):
            return False
        return float(row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0) >= cls._OUTCOME_BIAS_POSITIVE_RATE

    @classmethod
    def _funnel_row_negative(cls, row: dict[str, Any]) -> bool:
        if not cls._funnel_row_mature(row):
            return False
        return float(row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0) <= cls._OUTCOME_BIAS_NEGATIVE_RATE

    @staticmethod
    def _mode_row_thin(row: dict[str, Any]) -> bool:
        if not row:
            return True
        if str(row.get("confidence") or "low") == "low":
            return True
        return "thin" in str(row.get("sample_note") or "").lower()

    @staticmethod
    def _family_row_thin(row: dict[str, Any]) -> bool:
        if not row:
            return True
        if str(row.get("confidence") or "low") == "low":
            return True
        return "thin" in str(row.get("sample_note") or "").lower()

    def _mode_row_negative(self, row: dict[str, Any]) -> bool:
        if self._mode_row_thin(row):
            return False
        return str(row.get("advisory_state") or "") in {"watch", "research_only"}

    @staticmethod
    def _strategy_family_from_exposure(item: tuple[str, str] | dict[str, Any] | Plan) -> str:
        if isinstance(item, Plan):
            validity = dict(item.validity or {})
            return str(validity.get("strategy_family") or "unknown")
        if isinstance(item, dict):
            validity = dict(item.get("validity") or {})
            return str(item.get("strategy_family") or validity.get("strategy_family") or "unknown")
        return "unknown"

    @staticmethod
    def _session_name_from_row(row: dict[str, Any]) -> str:
        session_guidance = dict(row.get("session_guidance") or {})
        return str(session_guidance.get("session_name") or session_guidance.get("state") or "unknown")

    @classmethod
    def _capital_allocator_maturity(cls, closed: int) -> str:
        if closed >= cls._CAPITAL_ALLOCATOR_MATURE_MIN_CLOSED:
            return "mature"
        if closed >= cls._CAPITAL_ALLOCATOR_USABLE_MIN_CLOSED:
            return "usable"
        return "thin_sample"

    def _capital_allocator_modifier_state(
        self,
        *,
        funnel_row: dict[str, Any],
        mode_row: dict[str, Any],
    ) -> str:
        if not funnel_row and not mode_row:
            return "unavailable"
        if self._mode_row_negative(mode_row):
            return "negative"
        closed = int(funnel_row.get("closed", 0) or 0)
        rate = float(funnel_row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
        if closed >= self._CAPITAL_ALLOCATOR_USABLE_MIN_CLOSED and rate >= self._CAPITAL_ALLOCATOR_POSITIVE_RATE:
            return "positive"
        if closed >= self._CAPITAL_ALLOCATOR_USABLE_MIN_CLOSED and rate <= self._CAPITAL_ALLOCATOR_NEGATIVE_RATE:
            return "negative"
        return "neutral"

    @staticmethod
    def _accepted_allocated_risk(rows: list[dict[str, Any]], *, family: str | None = None) -> float:
        total = 0.0
        for row in rows:
            if family is not None and str(row.get("strategy_family") or dict(row.get("validity") or {}).get("strategy_family") or "unknown") != family:
                continue
            total += float(row.get("allocated_risk_r", row.get("recommended_risk_r", 0.0)) or 0.0)
        return total

    def _exposure_allocated_risk(
        self,
        exposures: list[tuple[str, str] | dict[str, Any] | Plan] | None,
        *,
        family: str | None = None,
    ) -> float:
        total = 0.0
        for item in exposures or []:
            if family is not None and self._strategy_family_from_exposure(item) != family:
                continue
            total += self._risk_from_exposure(item)
        return total

    def _build_capital_allocator(
        self,
        *,
        row: dict[str, Any],
        outcome_inputs_by_symbol: dict[str, dict[str, Any]] | None,
        existing_exposures: list[tuple[str, str] | dict[str, Any] | Plan] | None,
        accepted_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        base_recommended_risk_r = round(float(row.get("recommended_risk_r", 0.0) or 0.0), 4)
        symbol = str(row.get("symbol") or "").upper()
        family = str(row.get("strategy_family") or dict(row.get("validity") or {}).get("strategy_family") or "unknown")
        regime = str(row.get("regime") or dict(row.get("validity") or {}).get("regime") or "unknown")
        session_name = self._session_name_from_row(row)
        inputs = dict((outcome_inputs_by_symbol or {}).get(symbol) or {})

        unavailable_summary = {
            "available": bool(inputs),
            "applied": False,
            "tier": "neutral",
            "family": family,
            "maturity": "thin_sample" if inputs else "unavailable",
            "allocation_weight": 1.0,
            "risk_multiplier": 1.0,
            "base_recommended_risk_r": base_recommended_risk_r,
            "allocated_risk_r": base_recommended_risk_r,
            "capital_pressure": "neutral",
            "summary": "allocator evidence does not justify a capital tilt for this candidate",
            "reason_codes": [],
            "source_summary": {},
        }
        if base_recommended_risk_r <= 0.0:
            return unavailable_summary
        if not inputs:
            unavailable_summary["summary"] = "capital allocator unavailable; keep recommended risk unchanged"
            return unavailable_summary

        family_advisory = self._find_family_outcome_row(inputs.get("family_execution_degradation_advisory_summary"), family)
        family_mode = self._find_mode_bucket(inputs.get("mode_advisory_summary"), axis="family", bucket=family)
        regime_mode = self._find_mode_bucket(inputs.get("mode_advisory_summary"), axis="regime", bucket=regime)
        session_mode = self._find_mode_bucket(inputs.get("mode_advisory_summary"), axis="session", bucket=session_name)
        family_funnel = self._find_funnel_bucket(inputs.get("score_to_outcome_funnel_summary"), axis="family", bucket=family)
        regime_funnel = self._find_funnel_bucket(inputs.get("score_to_outcome_funnel_summary"), axis="regime", bucket=regime)
        session_funnel = self._find_funnel_bucket(inputs.get("score_to_outcome_funnel_summary"), axis="session", bucket=session_name)

        family_closed = int(family_funnel.get("closed", 0) or 0)
        family_maturity = self._capital_allocator_maturity(family_closed)
        family_execution_status = str(family_advisory.get("status") or "healthy")
        family_execution_thin = self._family_row_thin(family_advisory)
        family_mode_state = str(family_mode.get("advisory_state") or "keep_current_mode")
        family_mode_negative = self._mode_row_negative(family_mode)
        family_rate = float(family_funnel.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)

        family_state = "unavailable"
        if family_maturity == "thin_sample":
            family_state = "unavailable"
        elif family_execution_status == "manual_review" and not family_execution_thin:
            family_state = "negative"
        elif family_mode_negative:
            family_state = "negative"
        elif family_maturity == "mature" and family_rate >= self._CAPITAL_ALLOCATOR_POSITIVE_RATE:
            family_state = "positive"
        elif family_maturity == "mature" and family_rate <= self._CAPITAL_ALLOCATOR_NEGATIVE_RATE:
            family_state = "negative"
        else:
            family_state = "mixed"

        reason_codes: list[str] = []
        if family_maturity == "thin_sample":
            reason_codes.append("sample:thin_family_closed")
            tier = "neutral"
            allocation_weight = 1.0
        elif family_state == "positive":
            tier = "boost"
            allocation_weight = 1.15
            reason_codes.append("family_outcome:positive")
        elif family_state == "negative":
            tier = "reduce"
            allocation_weight = 0.7
            if family_execution_status == "manual_review" and not family_execution_thin:
                reason_codes.append("family_execution:manual_review")
            elif family_mode_negative:
                reason_codes.append(f"family_mode:{family_mode_state}")
            else:
                reason_codes.append("family_outcome:negative")
        else:
            tier = "neutral"
            allocation_weight = 1.0

        regime_state = self._capital_allocator_modifier_state(funnel_row=regime_funnel, mode_row=regime_mode)
        session_state = self._capital_allocator_modifier_state(funnel_row=session_funnel, mode_row=session_mode)

        for axis, state in (("regime", regime_state), ("session", session_state)):
            if state == "positive":
                if tier == "reduce":
                    allocation_weight += 0.025
                else:
                    allocation_weight += 0.05
                reason_codes.append(f"{axis}_modifier:positive")
            elif state == "negative":
                if tier != "reduce":
                    allocation_weight -= 0.05
                reason_codes.append(f"{axis}_modifier:negative")

        allocation_weight = round(clamp(allocation_weight, 0.6, 1.2), 4)
        if family_maturity == "thin_sample":
            risk_multiplier = 1.0
        elif allocation_weight >= 1.1:
            risk_multiplier = 1.1
        elif allocation_weight >= 1.0:
            risk_multiplier = 1.0
        elif allocation_weight >= 0.8:
            risk_multiplier = 0.9
        else:
            risk_multiplier = 0.75

        allocated_risk_r = round(base_recommended_risk_r * risk_multiplier, 4)
        active_allocated_risk = round(
            self._exposure_allocated_risk(existing_exposures)
            + self._accepted_allocated_risk(accepted_rows),
            4,
        )
        family_allocated_risk = round(
            self._exposure_allocated_risk(existing_exposures, family=family)
            + self._accepted_allocated_risk(accepted_rows, family=family),
            4,
        )
        capital_pressure = "neutral"
        if active_allocated_risk > 0.0 and tier == "boost" and (family_allocated_risk / active_allocated_risk) < 0.2:
            capital_pressure = "underallocated_positive"
        elif active_allocated_risk > 0.0 and tier == "reduce" and (family_allocated_risk / active_allocated_risk) > 0.4:
            capital_pressure = "overallocated_negative"
        if capital_pressure != "neutral":
            reason_codes.append(f"capital_pressure:{capital_pressure}")

        if tier == "boost":
            summary = "family post-cost outcome is stable and execution quality is healthy; modestly increase capital allowance"
        elif tier == "reduce":
            summary = "family execution quality or post-cost outcome is weak; reduce capital allowance before allocating scarce slots"
        else:
            summary = "allocator evidence does not justify a capital tilt for this candidate"
        if capital_pressure == "underallocated_positive":
            summary += "; positive family is still underallocated relative to current active risk"
        elif capital_pressure == "overallocated_negative":
            summary += "; negative family already consumes too much active risk"

        return {
            "available": True,
            "applied": tier != "neutral" or capital_pressure != "neutral",
            "tier": tier,
            "family": family,
            "maturity": family_maturity,
            "allocation_weight": allocation_weight,
            "risk_multiplier": round(risk_multiplier, 4),
            "base_recommended_risk_r": base_recommended_risk_r,
            "allocated_risk_r": allocated_risk_r,
            "capital_pressure": capital_pressure,
            "summary": summary,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "source_summary": {
                "family_closed": family_closed,
                "family_baseline_cost_profitable_rate_from_closed": round(family_rate, 4),
                "family_execution_status": family_execution_status or "healthy",
                "family_mode_advisory_state": family_mode_state or "keep_current_mode",
                "regime_modifier_state": regime_state,
                "session_modifier_state": session_state,
                "family_allocated_risk_r": family_allocated_risk,
                "active_allocated_risk_r": active_allocated_risk,
            },
        }

    def _build_outcome_bias(
        self,
        *,
        row: dict[str, Any],
        outcome_inputs_by_symbol: dict[str, dict[str, Any]] | None,
        session_name: str,
    ) -> dict[str, Any]:
        symbol = str(row.get("symbol") or "").upper()
        inputs = dict((outcome_inputs_by_symbol or {}).get(symbol) or {})
        if not inputs:
            return {
                "available": False,
                "applied": False,
                "tier": "neutral",
                "score_delta": 0.0,
                "summary": "outcome bias unavailable for this candidate",
                "reason_codes": [],
                "source_summary": {},
            }

        family = str(row.get("strategy_family") or dict(row.get("validity") or {}).get("strategy_family") or "unknown")
        regime = str(row.get("regime") or dict(row.get("validity") or {}).get("regime") or "unknown")

        family_advisory = self._find_family_outcome_row(inputs.get("family_execution_degradation_advisory_summary"), family)
        family_mode = self._find_mode_bucket(inputs.get("mode_advisory_summary"), axis="family", bucket=family)
        regime_mode = self._find_mode_bucket(inputs.get("mode_advisory_summary"), axis="regime", bucket=regime)
        session_mode = self._find_mode_bucket(inputs.get("mode_advisory_summary"), axis="session", bucket=session_name)
        family_funnel = self._find_funnel_bucket(inputs.get("score_to_outcome_funnel_summary"), axis="family", bucket=family)
        regime_funnel = self._find_funnel_bucket(inputs.get("score_to_outcome_funnel_summary"), axis="regime", bucket=regime)
        session_funnel = self._find_funnel_bucket(inputs.get("score_to_outcome_funnel_summary"), axis="session", bucket=session_name)

        family_status = str(family_advisory.get("status") or "healthy")
        family_adverse = family_status in {"manual_review", "watch"} and not self._family_row_thin(family_advisory)
        family_mode_negative = self._mode_row_negative(family_mode)

        family_state = "neutral"
        if family_adverse or family_mode_negative or self._funnel_row_negative(family_funnel):
            family_state = "negative"
        elif self._funnel_row_positive(family_funnel):
            family_state = "positive"

        regime_mode_negative = self._mode_row_negative(regime_mode)
        session_mode_negative = self._mode_row_negative(session_mode)

        regime_state = "neutral"
        if regime_mode_negative or self._funnel_row_negative(regime_funnel):
            regime_state = "negative"
        elif family_state != "negative" and self._funnel_row_positive(regime_funnel):
            regime_state = "positive"

        session_state = "neutral"
        if session_mode_negative or self._funnel_row_negative(session_funnel):
            session_state = "negative"
        elif family_state != "negative" and self._funnel_row_positive(session_funnel):
            session_state = "positive"

        score_delta = 0.0
        reason_codes: list[str] = []
        if family_state == "positive":
            score_delta += 2.5
            reason_codes.append("family_outcome:positive")
        elif family_state == "negative":
            score_delta -= 2.5
            reason_codes.append("family_outcome:negative")

        for axis, state in (("regime", regime_state), ("session", session_state)):
            if state == "positive":
                score_delta += 0.5
                reason_codes.append(f"{axis}_outcome:positive")
            elif state == "negative":
                score_delta -= 0.5
                reason_codes.append(f"{axis}_outcome:negative")

        score_delta = round(clamp(score_delta, -3.0, 3.0), 4)
        tier = "neutral"
        if score_delta > 0.0:
            tier = "positive"
            summary = "post-cost outcome alignment is stable; prefer this candidate when risk constraints are comparable"
        elif score_delta < 0.0:
            tier = "negative"
            summary = "post-cost outcome alignment is weak; deprioritize this candidate before allocating scarce slots"
        else:
            summary = "outcome data is present but does not justify a portfolio priority change"

        return {
            "available": True,
            "applied": abs(score_delta) > 0.0,
            "tier": tier,
            "score_delta": score_delta,
            "summary": summary,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "source_summary": {
                "family_closed": int(family_funnel.get("closed", 0) or 0),
                "family_baseline_cost_profitable_rate_from_closed": round(
                    float(family_funnel.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0), 4
                ),
                "regime_closed": int(regime_funnel.get("closed", 0) or 0),
                "regime_baseline_cost_profitable_rate_from_closed": round(
                    float(regime_funnel.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0), 4
                ),
                "session_closed": int(session_funnel.get("closed", 0) or 0),
                "session_baseline_cost_profitable_rate_from_closed": round(
                    float(session_funnel.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0), 4
                ),
                "family_degradation_status": family_status or "healthy",
                "family_mode_advisory_state": str(family_mode.get("advisory_state") or "keep_current_mode"),
                "regime_mode_advisory_state": str(regime_mode.get("advisory_state") or "keep_current_mode"),
                "session_mode_advisory_state": str(session_mode.get("advisory_state") or "keep_current_mode"),
            },
        }

    def _outcome_bias_sort_score(
        self,
        *,
        row: dict[str, Any],
        outcome_inputs_by_symbol: dict[str, dict[str, Any]] | None,
        session_name: str,
    ) -> float:
        base_score = float(row.get("final_rank_score", 0.0) or 0.0)
        bias = self._build_outcome_bias(
            row=row,
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
            session_name=session_name,
        )
        return round(base_score + float(bias.get("score_delta", 0.0) or 0.0), 4)

    def _apply_outcome_sizing_adjustment(
        self,
        *,
        row: dict[str, Any],
        outcome_inputs_by_symbol: dict[str, dict[str, Any]] | None,
    ) -> None:
        strategy_sizing = dict(row.get("strategy_sizing") or {})
        base_final_risk_r = float(strategy_sizing.get("final_risk_r", 0.0) or 0.0)
        symbol = str(row.get("symbol") or "").upper()
        inputs = dict((outcome_inputs_by_symbol or {}).get(symbol) or {})

        if not strategy_sizing:
            return

        default_adjustment = {
            "available": bool(inputs),
            "applied": False,
            "status": "healthy",
            "penalty_tier": "none",
            "base_final_risk_r": round(base_final_risk_r, 4),
            "multiplier": 1.0,
            "final_risk_r": round(base_final_risk_r, 4),
            "reason_codes": [],
            "summary": "outcome-aware sizing adjustment found no material degradation or post-cost weakness",
            "source_summary": {},
        }
        if not inputs or base_final_risk_r <= 0.0:
            strategy_sizing["base_final_risk_r"] = round(base_final_risk_r, 4)
            strategy_sizing["outcome_risk_adjustment"] = default_adjustment
            row["strategy_sizing"] = strategy_sizing
            row["recommended_risk_r"] = round(base_final_risk_r, 4)
            row["expected_ev_at_recommended_size_r"] = round(
                float(row.get("expected_ev_r", 0.0) or 0.0) * float(row.get("recommended_risk_r", 0.0) or 0.0),
                4,
            )
            return

        family = str(row.get("strategy_family") or dict(row.get("validity") or {}).get("strategy_family") or "unknown")
        regime = str(row.get("regime") or dict(row.get("validity") or {}).get("regime") or "unknown")
        session_name = str(((row.get("session_guidance") or {}).get("session_name") or (row.get("session_guidance") or {}).get("state") or "unknown"))

        family_advisory = self._find_family_outcome_row(inputs.get("family_execution_degradation_advisory_summary"), family)
        family_mode = self._find_mode_bucket(inputs.get("mode_advisory_summary"), axis="family", bucket=family)
        regime_mode = self._find_mode_bucket(inputs.get("mode_advisory_summary"), axis="regime", bucket=regime)
        session_mode = self._find_mode_bucket(inputs.get("mode_advisory_summary"), axis="session", bucket=session_name)
        family_funnel = self._find_funnel_bucket(inputs.get("score_to_outcome_funnel_summary"), axis="family", bucket=family)
        regime_funnel = self._find_funnel_bucket(inputs.get("score_to_outcome_funnel_summary"), axis="regime", bucket=regime)
        session_funnel = self._find_funnel_bucket(inputs.get("score_to_outcome_funnel_summary"), axis="session", bucket=session_name)

        multiplier = 1.0
        status = "healthy"
        penalty_tier = "none"
        reason_codes: list[str] = []

        family_status = str(family_advisory.get("status") or "healthy")
        if family_status == "manual_review" and not self._family_row_thin(family_advisory):
            multiplier = min(multiplier, 0.5)
            status = "manual_review"
            penalty_tier = "hard_clamp"
            reason_codes.append("family_execution_degradation:manual_review")
        elif family_status == "watch" and not self._family_row_thin(family_advisory):
            multiplier = min(multiplier, 0.75)
            status = "watch"
            penalty_tier = "soft_clamp"
            reason_codes.append("family_execution_degradation:watch")

        family_closed = int(family_funnel.get("closed", 0) or 0)
        family_rate = float(family_funnel.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
        if family_closed >= 4 and family_rate <= 0.3:
            multiplier = min(multiplier, 0.5)
            status = "manual_review"
            penalty_tier = "hard_clamp"
            reason_codes.append("post_cost_conversion:weak_family_alignment")

        for axis, mode_row in (("family", family_mode), ("regime", regime_mode), ("session", session_mode)):
            advisory_state = str(mode_row.get("advisory_state") or "")
            if advisory_state in {"watch", "research_only"} and not self._mode_row_thin(mode_row):
                multiplier = min(multiplier, 0.75)
                if penalty_tier == "none":
                    penalty_tier = "soft_clamp"
                    status = "watch"
                reason_codes.append(f"mode_advisory:{axis}:{advisory_state}")

        for axis, funnel_row in (("regime", regime_funnel), ("session", session_funnel)):
            closed = int(funnel_row.get("closed", 0) or 0)
            rate = float(funnel_row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
            if closed >= 4 and rate <= 0.3:
                multiplier = min(multiplier, 0.75)
                if penalty_tier == "none":
                    penalty_tier = "soft_clamp"
                    status = "watch"
                reason_codes.append(f"{axis}_outcome:weak_alignment")

        final_risk_r = round(base_final_risk_r * multiplier, 4)
        if penalty_tier == "hard_clamp":
            summary = "family execution quality or post-cost conversion is weak; reduce live risk allowance materially"
        elif penalty_tier == "soft_clamp":
            summary = "family or bucket-level outcome signals are drifting; reduce live risk allowance"
        else:
            summary = default_adjustment["summary"]

        adjustment = {
            "available": True,
            "applied": multiplier < 1.0,
            "status": status,
            "penalty_tier": penalty_tier,
            "base_final_risk_r": round(base_final_risk_r, 4),
            "multiplier": round(multiplier, 4),
            "final_risk_r": final_risk_r,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "summary": summary,
            "source_summary": {
                "family_status": family_status or "healthy",
                "mode_advisory_state": str((family_mode or regime_mode or session_mode or {}).get("advisory_state") or "keep_current_mode"),
                "family_closed_count": family_closed,
                "family_baseline_cost_profitable_rate_from_closed": round(family_rate, 4),
            },
        }

        strategy_sizing["base_final_risk_r"] = round(base_final_risk_r, 4)
        strategy_sizing["final_risk_r"] = final_risk_r
        strategy_sizing["outcome_risk_adjustment"] = adjustment
        row["strategy_sizing"] = strategy_sizing
        row["recommended_risk_r"] = final_risk_r
        row["expected_ev_at_recommended_size_r"] = round(
            float(row.get("expected_ev_r", 0.0) or 0.0) * float(final_risk_r),
            4,
        )

    def assess_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        existing_exposures: list[tuple[str, str] | dict[str, Any] | Plan] | None = None,
        today_trade_count: int = 0,
        operating_lock: dict[str, Any] | None = None,
        outcome_inputs_by_symbol: dict[str, dict[str, Any]] | None = None,
        apply_outcome_bias: bool = False,
    ) -> list[dict[str, Any]]:
        exposures = self._normalize_exposures(existing_exposures)
        thesis_clusters = self._build_thesis_clusters(exposures)
        mode_policy = self.mode.policy()
        session_guidance = self.session_guidance.snapshot(
            operating_lock=operating_lock,
            strategy_mode=mode_policy.mode,
        )
        session_penalty = float(session_guidance.get("soft_penalty", 0.0) or 0.0)
        current_total_risk_r = sum(self._risk_from_exposure(item) for item in existing_exposures or [])
        if not self.settings.portfolio_overlay_enabled:
            assessed: list[dict[str, Any]] = []
            accepted_count = 0
            accepted_rows: list[dict[str, Any]] = []
            current_total_risk_local = float(current_total_risk_r)
            for item in sorted(rows, key=lambda value: float(value.get("final_rank_score", 0.0)), reverse=True):
                row = dict(item)
                thesis_fingerprint = self.thesis.build_from_candidate(row)
                matched_cluster = self._matching_cluster(thesis_clusters, thesis_fingerprint)
                row["accepted"] = True
                row["block_reason"] = None
                row["block_reason_message"] = None
                row["regime"] = self._regime_label(row)
                row["base_rank_score"] = round(float(item.get("final_rank_score", 0.0)), 4)
                row["adjusted_rank_score"] = round(float(item.get("final_rank_score", 0.0)), 4)
                row["portfolio_penalty"] = round(float(item.get("portfolio_penalty", 0.0)), 4)
                row["portfolio_high_corr_count"] = int(item.get("portfolio_high_corr_count", 0) or 0)
                row["risk_budget_score"] = round(float(item.get("risk_budget_score", 100.0)), 4)
                row["portfolio_volatility"] = round(float(item.get("portfolio_volatility", 0.0)), 6)
                row["portfolio_total_cap"] = int(item.get("portfolio_total_cap", 0) or 0)
                row["portfolio_directional_cap"] = int(item.get("portfolio_directional_cap", 0) or 0)
                row["portfolio_cluster_cap"] = int(item.get("portfolio_cluster_cap", 0) or 0)
                row["projected_total_exposure"] = 0
                row["projected_directional_exposure"] = 0
                row["projected_cluster_exposure"] = 0
                row["strategy_mode"] = mode_policy.mode.value
                row["mode_shadow_only"] = bool(mode_policy.shadow_only)
                row["mode_today_trade_count"] = int(today_trade_count)
                row["mode_daily_trade_limit"] = int(mode_policy.max_daily_trades)
                row["mode_current_total_risk_r"] = round(float(current_total_risk_local), 4)
                row["mode_total_risk_cap_r"] = float(mode_policy.max_total_risk_r)
                row["thesis_active_cluster_count"] = len(thesis_clusters)
                row["session_guidance"] = dict(session_guidance)
                row["session_penalty"] = round(session_penalty, 4)
                validity = dict(row.get("validity") or {})
                row["reaction_evidence"] = validity.get("reaction_evidence")
                row["location_reference"] = validity.get("location_reference")
                row["session_liquidity_reference"] = validity.get("session_liquidity_reference")
                self._reset_alpha_research_fields(row)
                self._attach_thesis_fields(row=row, fingerprint=thesis_fingerprint, cluster=matched_cluster)
                row["strategy_sizing"] = self.sizing.evaluate_from_row(row, active_thesis_clusters=len(thesis_clusters))
                row["recommended_risk_r"] = float(row["strategy_sizing"].get("final_risk_r", 0.0) or 0.0)
                row["strategy_sizing"] = self.mode.apply_to_sizing(row["strategy_sizing"], mode=mode_policy.mode)
                row["recommended_risk_r"] = float(row["strategy_sizing"].get("final_risk_r", 0.0) or 0.0)
                self._apply_outcome_sizing_adjustment(row=row, outcome_inputs_by_symbol=outcome_inputs_by_symbol)
                capital_allocator = self._build_capital_allocator(
                    row=row,
                    outcome_inputs_by_symbol=outcome_inputs_by_symbol,
                    existing_exposures=existing_exposures,
                    accepted_rows=accepted_rows,
                )
                row["capital_allocator"] = capital_allocator
                row["allocation_weight"] = float(capital_allocator.get("allocation_weight", 1.0) or 1.0)
                row["allocated_risk_r"] = float(
                    capital_allocator.get("allocated_risk_r", row.get("recommended_risk_r", 0.0)) or row.get("recommended_risk_r", 0.0) or 0.0
                )
                row["capital_pressure"] = str(capital_allocator.get("capital_pressure", "neutral") or "neutral")
                row["mode_projected_trade_count"] = int(today_trade_count) + accepted_count + 1
                row["mode_projected_total_risk_r"] = round(float(current_total_risk_local) + float(row.get("recommended_risk_r", 0.0) or 0.0), 4)
                pre_outcome_final_rank_score = round(
                    float(row.get("adjusted_rank_score", row.get("final_rank_score", 0.0))) - session_penalty,
                    4,
                )
                if apply_outcome_bias:
                    outcome_bias = self._build_outcome_bias(
                        row=row,
                        outcome_inputs_by_symbol=outcome_inputs_by_symbol,
                        session_name=str(session_guidance.get("session_name") or session_guidance.get("state") or "unknown"),
                    )
                    row["outcome_bias_score"] = float(outcome_bias.get("score_delta", 0.0) or 0.0)
                    row["outcome_bias"] = outcome_bias
                    row["pre_outcome_final_rank_score"] = pre_outcome_final_rank_score
                    row["post_outcome_final_rank_score"] = round(
                        pre_outcome_final_rank_score + float(outcome_bias.get("score_delta", 0.0) or 0.0),
                        4,
                    )
                    row["final_rank_score"] = float(row["post_outcome_final_rank_score"])
                else:
                    row["final_rank_score"] = pre_outcome_final_rank_score
                if mode_policy.shadow_only:
                    row["accepted"] = False
                    row["block_reason"] = "mode_shadow_only"
                    row["block_reason_message"] = block_reason_message(row["block_reason"])
                elif self.mode.daily_limit_reached(
                    today_trade_count=today_trade_count,
                    accepted_candidates=accepted_count,
                    mode=mode_policy.mode,
                ):
                    row["accepted"] = False
                    row["block_reason"] = "mode_daily_trade_limit_reached"
                    row["block_reason_message"] = block_reason_message(row["block_reason"])
                elif self.mode.projected_total_risk_exceeded(
                    current_total_risk_r=current_total_risk_local,
                    candidate_risk_r=float(row.get("recommended_risk_r", 0.0) or 0.0),
                    mode=mode_policy.mode,
                ):
                    row["accepted"] = False
                    row["block_reason"] = "mode_total_risk_cap_reached"
                    row["block_reason_message"] = block_reason_message(row["block_reason"])
                elif row["accepted"]:
                    accepted_count += 1
                    current_total_risk_local += float(row.get("recommended_risk_r", 0.0) or 0.0)
                    accepted_rows.append(row)
                    row["block_reason_message"] = None
                assessed.append(row)
            return assessed

        self._reset_cache()

        if apply_outcome_bias:
            session_name = str(session_guidance.get("session_name") or session_guidance.get("state") or "unknown")
            candidates = sorted(
                rows,
                key=lambda item: self._outcome_bias_sort_score(
                    row=item,
                    outcome_inputs_by_symbol=outcome_inputs_by_symbol,
                    session_name=session_name,
                ),
                reverse=True,
            )
        else:
            candidates = sorted(rows, key=lambda item: float(item.get("final_rank_score", 0.0)), reverse=True)
        assessed: list[dict[str, Any]] = []
        accepted: list[dict[str, Any]] = []

        for item in candidates:
            row = dict(item)
            symbol = str(item.get("symbol", "")).upper()
            direction = str(item.get("direction", "")).lower()
            thesis_fingerprint = self.thesis.build_from_candidate(row)
            matched_thesis = self._matching_cluster(thesis_clusters, thesis_fingerprint)
            base_score = round(float(item.get("final_rank_score", 0.0)), 4)
            row["base_rank_score"] = base_score
            row["accepted"] = False
            row["block_reason"] = "invalid_candidate"
            row["block_reason_message"] = block_reason_message(row["block_reason"])
            row["adjusted_rank_score"] = base_score
            row["projected_total_exposure"] = len(exposures) + len(accepted)
            row["projected_directional_exposure"] = 0
            row["projected_cluster_exposure"] = 0
            row["portfolio_penalty"] = round(float(item.get("portfolio_penalty", 0.0)), 4)
            row["portfolio_high_corr_count"] = int(item.get("portfolio_high_corr_count", 0) or 0)
            row["risk_budget_score"] = round(float(item.get("risk_budget_score", 100.0)), 4)
            row["portfolio_volatility"] = round(float(item.get("portfolio_volatility", 0.0)), 6)
            row["portfolio_total_cap"] = int(item.get("portfolio_total_cap", 0) or 0)
            row["portfolio_directional_cap"] = int(item.get("portfolio_directional_cap", 0) or 0)
            row["portfolio_cluster_cap"] = int(item.get("portfolio_cluster_cap", 0) or 0)
            row["strategy_mode"] = mode_policy.mode.value
            row["mode_shadow_only"] = bool(mode_policy.shadow_only)
            row["mode_today_trade_count"] = int(today_trade_count)
            row["mode_daily_trade_limit"] = int(mode_policy.max_daily_trades)
            row["mode_current_total_risk_r"] = round(float(current_total_risk_r), 4)
            row["mode_total_risk_cap_r"] = float(mode_policy.max_total_risk_r)
            row["thesis_active_cluster_count"] = len(thesis_clusters)
            row["session_guidance"] = dict(session_guidance)
            row["session_penalty"] = round(session_penalty, 4)
            validity = dict(row.get("validity") or {})
            row["reaction_evidence"] = validity.get("reaction_evidence")
            row["location_reference"] = validity.get("location_reference")
            row["session_liquidity_reference"] = validity.get("session_liquidity_reference")
            self._reset_alpha_research_fields(row)
            self._attach_thesis_fields(row=row, fingerprint=thesis_fingerprint, cluster=matched_thesis)
            row["strategy_sizing"] = self.sizing.evaluate_from_row(row, active_thesis_clusters=len(thesis_clusters))
            row["recommended_risk_r"] = float(row["strategy_sizing"].get("final_risk_r", 0.0) or 0.0)
            row["strategy_sizing"] = self.mode.apply_to_sizing(row["strategy_sizing"], mode=mode_policy.mode)
            row["recommended_risk_r"] = float(row["strategy_sizing"].get("final_risk_r", 0.0) or 0.0)
            self._apply_outcome_sizing_adjustment(row=row, outcome_inputs_by_symbol=outcome_inputs_by_symbol)
            capital_allocator = self._build_capital_allocator(
                row=row,
                outcome_inputs_by_symbol=outcome_inputs_by_symbol,
                existing_exposures=existing_exposures,
                accepted_rows=accepted,
            )
            row["capital_allocator"] = capital_allocator
            row["allocation_weight"] = float(capital_allocator.get("allocation_weight", 1.0) or 1.0)
            row["allocated_risk_r"] = float(
                capital_allocator.get("allocated_risk_r", row.get("recommended_risk_r", 0.0)) or row.get("recommended_risk_r", 0.0) or 0.0
            )
            row["capital_pressure"] = str(capital_allocator.get("capital_pressure", "neutral") or "neutral")

            if not symbol or direction not in {"long", "short"}:
                assessed.append(row)
                continue

            regime = self._regime_label(item)
            caps = self._budget_caps(regime)
            total_exposure = len(exposures) + len(accepted)
            directional_exposure = len([e for e in exposures if e.direction == direction]) + len(
                [a for a in accepted if str(a.get("direction", "")).lower() == direction]
            )
            same_direction_symbols = [e.symbol for e in exposures if e.direction == direction] + [
                str(a.get("symbol", "")).upper() for a in accepted if str(a.get("direction", "")).lower() == direction
            ]
            high_corr_count = 0
            corr_values: list[float] = []
            for other in same_direction_symbols:
                corr = 1.0 if other == symbol else self._correlation(symbol, other)
                if corr is None:
                    continue
                corr_values.append(corr)
                if corr >= self.settings.portfolio_overlay_high_corr_threshold:
                    high_corr_count += 1

            avg_positive_corr = fmean(max(0.0, value) for value in corr_values) if corr_values else 0.0
            corr_penalty = (
                high_corr_count * self.settings.portfolio_overlay_penalty_per_high_corr
                + avg_positive_corr * self.settings.portfolio_overlay_penalty_corr_scale
            )
            volatility = self._volatility(symbol)
            volatility_penalty = self._volatility_penalty(volatility)
            regime_penalty = self._regime_penalty(regime)
            projected_total = total_exposure + 1
            projected_directional = directional_exposure + 1
            projected_cluster = high_corr_count + 1
            exposure_penalty = self._exposure_penalty(
                projected_total=projected_total,
                projected_directional=projected_directional,
                high_corr_count=high_corr_count,
                caps=caps,
            )
            penalty = corr_penalty + volatility_penalty + regime_penalty + exposure_penalty
            risk_budget_score = round(clamp(100.0 - penalty, 0.0, 100.0), 4)
            adjusted_score = round(base_score - penalty, 4)

            row["regime"] = regime
            row["portfolio_penalty"] = round(penalty, 4)
            row["portfolio_high_corr_count"] = int(high_corr_count)
            row["risk_budget_score"] = risk_budget_score
            row["portfolio_volatility"] = round(volatility, 6)
            row["portfolio_total_cap"] = int(caps.total)
            row["portfolio_directional_cap"] = int(caps.directional)
            row["portfolio_cluster_cap"] = int(caps.cluster)
            row["projected_total_exposure"] = int(projected_total)
            row["projected_directional_exposure"] = int(projected_directional)
            row["projected_cluster_exposure"] = int(projected_cluster)
            row["adjusted_rank_score"] = adjusted_score
            pre_outcome_final_rank_score = round(adjusted_score - session_penalty, 4)
            if apply_outcome_bias:
                outcome_bias = self._build_outcome_bias(
                    row=row,
                    outcome_inputs_by_symbol=outcome_inputs_by_symbol,
                    session_name=str(session_guidance.get("session_name") or session_guidance.get("state") or "unknown"),
                )
                row["outcome_bias_score"] = float(outcome_bias.get("score_delta", 0.0) or 0.0)
                row["outcome_bias"] = outcome_bias
                row["pre_outcome_final_rank_score"] = pre_outcome_final_rank_score
                row["post_outcome_final_rank_score"] = round(
                    pre_outcome_final_rank_score + float(outcome_bias.get("score_delta", 0.0) or 0.0),
                    4,
                )
                row["final_rank_score"] = float(row["post_outcome_final_rank_score"])
            else:
                row["final_rank_score"] = pre_outcome_final_rank_score

            if self.settings.thesis_dedupe_enabled and thesis_fingerprint and matched_thesis is not None:
                row["block_reason"] = "thesis_duplicate_blocked"
                row["block_reason_message"] = block_reason_message(row["block_reason"])
                row["thesis_rejected_reason"] = "duplicate_active_thesis"
                row["thesis_cluster_size"] = len(matched_thesis.members) + 1
                assessed.append(row)
                continue
            if (
                self.settings.thesis_dedupe_enabled
                and thesis_fingerprint
                and matched_thesis is None
                and len(thesis_clusters) >= self.settings.thesis_max_active_clusters
            ):
                row["block_reason"] = "thesis_active_cap_reached"
                row["block_reason_message"] = block_reason_message(row["block_reason"])
                row["thesis_rejected_reason"] = "active_thesis_cluster_cap"
                assessed.append(row)
                continue
            projected_trade_count = int(today_trade_count) + len(accepted) + 1
            row["mode_projected_trade_count"] = projected_trade_count
            row["mode_projected_total_risk_r"] = round(float(current_total_risk_r) + float(row.get("recommended_risk_r", 0.0) or 0.0), 4)
            if mode_policy.shadow_only:
                row["block_reason"] = "mode_shadow_only"
                row["block_reason_message"] = block_reason_message(row["block_reason"])
                assessed.append(row)
                continue
            if self.mode.daily_limit_reached(
                today_trade_count=today_trade_count,
                accepted_candidates=len(accepted),
                mode=mode_policy.mode,
            ):
                row["block_reason"] = "mode_daily_trade_limit_reached"
                row["block_reason_message"] = block_reason_message(row["block_reason"])
                assessed.append(row)
                continue
            if float(row.get("recommended_risk_r", 0.0) or 0.0) <= 0.0:
                row["block_reason"] = str((row.get("strategy_sizing") or {}).get("blocked_reason") or "sizing_zero_risk")
                row["block_reason_message"] = block_reason_message(row["block_reason"])
                assessed.append(row)
                continue
            if self.mode.projected_total_risk_exceeded(
                current_total_risk_r=current_total_risk_r,
                candidate_risk_r=float(row.get("recommended_risk_r", 0.0) or 0.0),
                mode=mode_policy.mode,
            ):
                row["block_reason"] = "mode_total_risk_cap_reached"
                row["block_reason_message"] = block_reason_message(row["block_reason"])
                assessed.append(row)
                continue
            if total_exposure >= caps.total:
                row["block_reason"] = "total_cap_reached"
                row["block_reason_message"] = block_reason_message(row["block_reason"])
                assessed.append(row)
                continue
            if directional_exposure >= caps.directional:
                row["block_reason"] = "directional_cap_reached"
                row["block_reason_message"] = block_reason_message(row["block_reason"])
                assessed.append(row)
                continue
            if high_corr_count >= caps.cluster:
                row["block_reason"] = "cluster_cap_reached"
                row["block_reason_message"] = block_reason_message(row["block_reason"])
                assessed.append(row)
                continue
            if risk_budget_score < self.settings.portfolio_overlay_min_risk_budget_score:
                row["block_reason"] = "risk_budget_below_min"
                row["block_reason_message"] = block_reason_message(row["block_reason"])
                self._maybe_route_to_alpha_research(row=row, reason=row["block_reason"])
                assessed.append(row)
                continue
            if adjusted_score <= 0.0:
                row["block_reason"] = "adjusted_score_non_positive"
                row["block_reason_message"] = block_reason_message(row["block_reason"])
                self._maybe_route_to_alpha_research(row=row, reason=row["block_reason"])
                assessed.append(row)
                continue

            row["accepted"] = True
            row["block_reason"] = None
            row["block_reason_message"] = None
            row["thesis_rejected_reason"] = None
            current_total_risk_r = float(current_total_risk_r) + float(row.get("recommended_risk_r", 0.0) or 0.0)
            accepted.append(row)
            if self.settings.thesis_dedupe_enabled and thesis_fingerprint:
                matched_or_new = self._matching_cluster(thesis_clusters, thesis_fingerprint)
                if matched_or_new is None:
                    matched_or_new = _ThesisCluster(
                        cluster_id=self.thesis.thesis_cluster_id(thesis_fingerprint),
                        primary_symbol=symbol,
                        primary_priority=self._priority_signature(row),
                        fingerprints=[thesis_fingerprint],
                        members=[symbol],
                    )
                    thesis_clusters.append(matched_or_new)
                else:
                    matched_or_new.fingerprints.append(thesis_fingerprint)
                    if symbol not in matched_or_new.members:
                        matched_or_new.members.append(symbol)
                row["thesis_active_cluster_count"] = len(thesis_clusters)
                self._attach_thesis_fields(row=row, fingerprint=thesis_fingerprint, cluster=matched_or_new)
            assessed.append(row)

        return assessed

    def filter_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        limit: int,
        existing_exposures: list[tuple[str, str] | dict[str, Any] | Plan] | None = None,
        today_trade_count: int = 0,
        operating_lock: dict[str, Any] | None = None,
        outcome_inputs_by_symbol: dict[str, dict[str, Any]] | None = None,
        apply_outcome_bias: bool = False,
    ) -> list[dict[str, Any]]:
        assessed = self.assess_rows(
            rows,
            existing_exposures=existing_exposures,
            today_trade_count=today_trade_count,
            operating_lock=operating_lock,
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
            apply_outcome_bias=apply_outcome_bias,
        )
        accepted = [row for row in assessed if bool(row.get("accepted"))]
        accepted.sort(key=lambda item: float(item.get("final_rank_score", 0.0)), reverse=True)
        return accepted[:limit]

    @staticmethod
    def _regime_label(item: dict[str, Any]) -> str:
        regime = str(item.get("regime", "range")).lower()
        if regime in {"trend", "range", "shock"}:
            return regime
        return "range"

    def _budget_caps(self, regime: str) -> _BudgetCaps:
        multiplier = {
            "trend": float(self.settings.portfolio_overlay_cap_multiplier_trend),
            "shock": float(self.settings.portfolio_overlay_cap_multiplier_shock),
        }.get(regime, float(self.settings.portfolio_overlay_cap_multiplier_range))
        multiplier = clamp(multiplier, 0.2, 1.0)
        return _BudgetCaps(
            total=max(1, int(self.settings.portfolio_overlay_max_total_exposure * multiplier)),
            directional=max(1, int(self.settings.portfolio_overlay_max_directional_exposure * multiplier)),
            cluster=max(1, int(self.settings.portfolio_overlay_max_cluster_exposure * multiplier)),
        )

    def _regime_penalty(self, regime: str) -> float:
        return {
            "trend": float(self.settings.portfolio_overlay_regime_penalty_trend),
            "shock": float(self.settings.portfolio_overlay_regime_penalty_shock),
        }.get(regime, float(self.settings.portfolio_overlay_regime_penalty_range))

    def _volatility_penalty(self, volatility: float) -> float:
        target = max(1e-9, float(self.settings.portfolio_overlay_volatility_target))
        hard_cap = max(target, float(self.settings.portfolio_overlay_volatility_hard_cap))
        scale = float(self.settings.portfolio_overlay_penalty_volatility_scale)

        ratio_penalty = max(0.0, (volatility / target) - 1.0) * scale
        hard_cap_penalty = 0.0
        if volatility > hard_cap:
            hard_cap_penalty = ((volatility - hard_cap) / hard_cap) * scale
        return ratio_penalty + hard_cap_penalty

    def _exposure_penalty(
        self,
        *,
        projected_total: int,
        projected_directional: int,
        high_corr_count: int,
        caps: _BudgetCaps,
    ) -> float:
        utilization = max(
            projected_total / max(1, caps.total),
            projected_directional / max(1, caps.directional),
            (high_corr_count + 1) / max(1, caps.cluster),
        )
        excess = max(0.0, utilization - 0.55)
        return excess * float(self.settings.portfolio_overlay_penalty_exposure_scale)

    def _correlation(self, symbol_a: str, symbol_b: str) -> float | None:
        key = tuple(sorted((symbol_a, symbol_b)))
        if key in self._corr_cache:
            return self._corr_cache[key]

        returns_a = self._returns(symbol_a)
        returns_b = self._returns(symbol_b)
        if not returns_a or not returns_b:
            self._corr_cache[key] = None
            return None

        shared_ts = sorted(set(returns_a.keys()) & set(returns_b.keys()))
        if len(shared_ts) < self.settings.portfolio_overlay_min_overlap_bars:
            self._corr_cache[key] = None
            return None

        xs = [returns_a[ts] for ts in shared_ts]
        ys = [returns_b[ts] for ts in shared_ts]
        mean_x = fmean(xs)
        mean_y = fmean(ys)
        var_x = sum((value - mean_x) ** 2 for value in xs)
        var_y = sum((value - mean_y) ** 2 for value in ys)
        if var_x <= 1e-12 or var_y <= 1e-12:
            self._corr_cache[key] = None
            return None

        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        corr = max(-1.0, min(1.0, cov / (var_x**0.5 * var_y**0.5)))
        self._corr_cache[key] = corr
        return corr

    def _returns(self, symbol: str) -> dict[datetime, float]:
        if symbol in self._returns_cache:
            return self._returns_cache[symbol]

        if self.candle_repo is None:
            self._returns_cache[symbol] = {}
            return {}

        candles = self.candle_repo.list_recent(
            symbol=symbol,
            timeframe="5m",
            limit=max(10, self.settings.portfolio_overlay_window_bars + 1),
        )
        if len(candles) < 3:
            self._returns_cache[symbol] = {}
            return {}

        result: dict[datetime, float] = {}
        prev_close: float | None = None
        for candle in candles:
            close = float(candle.c)
            if prev_close is not None and prev_close > 1e-12:
                result[candle.ts] = (close - prev_close) / prev_close
            prev_close = close

        self._returns_cache[symbol] = result
        return result

    def _volatility(self, symbol: str) -> float:
        if symbol in self._vol_cache:
            return self._vol_cache[symbol]

        returns = list(self._returns(symbol).values())
        if len(returns) < 3:
            self._vol_cache[symbol] = 0.0
            return 0.0

        volatility = float(pstdev(returns))
        self._vol_cache[symbol] = volatility
        return volatility
