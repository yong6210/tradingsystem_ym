from __future__ import annotations

from math import isfinite
from typing import Any

from app.core.config import Settings, get_settings


class ExecutionDegradationAdvisoryService:
    _MIN_MATURED_FOR_FILL_WATCH = 4
    _MIN_MATURED_FOR_FILL_MANUAL = 8
    _MIN_CLOSED_FOR_FAILURE_WATCH = 4
    _MIN_CLOSED_FOR_FAILURE_MANUAL = 6

    _FILL_RATE_WATCH = 0.55
    _FILL_RATE_MANUAL = 0.35
    _FORCED_EXIT_WATCH = 0.30
    _FORCED_EXIT_MANUAL = 0.45
    _INFO_FAILURE_WATCH = 0.15
    _INFO_FAILURE_MANUAL = 0.25
    _TIME_FAILURE_WATCH = 0.20
    _TIME_FAILURE_MANUAL = 0.35

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if isfinite(parsed) else default

    def _slippage_thresholds(self) -> dict[str, float]:
        manual = self._safe_float(self.settings.auto_trading_max_slippage_bps, default=12.0)
        watch = max(6.0, round(manual * 0.7, 4))
        return {
            "watch_slippage_p95_bps": watch,
            "manual_review_slippage_p95_bps": manual,
        }

    @staticmethod
    def _reason(
        *,
        code: str,
        severity: str,
        message: str,
        evidence: dict[str, Any] | None = None,
        recommended_action: str,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "message": message,
            "evidence": dict(evidence or {}),
            "recommended_action": recommended_action,
        }

    @staticmethod
    def _severity_rank(value: str) -> int:
        order = {"healthy": 0, "watch": 1, "manual_review": 2}
        return int(order.get(str(value), 0))

    def _overall_status(self, reasons: list[dict[str, Any]]) -> str:
        if not reasons:
            return "healthy"
        return max(
            (str(item.get("severity") or "healthy") for item in reasons),
            key=self._severity_rank,
        )

    @staticmethod
    def _summary_for_status(status: str) -> str:
        if status == "manual_review":
            return "execution quality degradation requires manual review before expanding new live entries"
        if status == "watch":
            return "execution quality is drifting; review cost, fill, and exit-failure mix before scaling"
        return "execution quality is within current advisory tolerance"

    @staticmethod
    def _recommended_action_for_status(status: str) -> str:
        if status == "manual_review":
            return "require_manual_review_before_new_live_entries"
        if status == "watch":
            return "review_execution_drag_and_hold_size"
        return "continue_runtime_monitoring"

    def generate(
        self,
        *,
        execution_quality: dict[str, Any] | None,
        performance_decomposition_summary: dict[str, Any] | None,
        strategy_v2_stress_validation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        execution_payload = dict(execution_quality or {})
        performance_payload = dict(performance_decomposition_summary or {})
        stress_payload = dict(strategy_v2_stress_validation or {})

        if not any([execution_payload, performance_payload, stress_payload]):
            return {
                "available": False,
                "status": "healthy",
                "healthy": True,
                "summary": "execution degradation advisory unavailable",
                "recommended_action": "continue_runtime_monitoring",
                "reason_codes": [],
                "reasons": [],
                "thresholds": self._slippage_thresholds(),
                "advisory_only": True,
            }

        reasons: list[dict[str, Any]] = []
        slippage_thresholds = self._slippage_thresholds()

        matured_plans = int(execution_payload.get("plans_matured", 0) or 0)
        fill_events_total = int(execution_payload.get("fill_events_total", 0) or 0)
        fill_rate = float(execution_payload.get("fill_rate", 0.0) or 0.0)
        slippage_bps = dict(execution_payload.get("slippage_bps") or {})
        slippage_p95 = float(slippage_bps.get("p95", 0.0) or 0.0)
        forced_exit_ratio = float(execution_payload.get("forced_exit_ratio", 0.0) or 0.0)
        information_failure_ratio = float(execution_payload.get("information_failure_ratio", 0.0) or 0.0)
        time_failure_ratio = float(execution_payload.get("time_failure_ratio", 0.0) or 0.0)
        closed_plans = int(
            sum(int((payload or {}).get("closed", 0) or 0) for payload in dict(execution_payload.get("by_strategy_family") or {}).values())
        )

        if matured_plans <= 0:
            reasons.append(
                self._reason(
                    code="execution_quality_low_coverage",
                    severity="watch",
                    message="no matured plans yet; execution degradation advisory is low-confidence",
                    evidence={"plans_matured": matured_plans, "fill_events_total": fill_events_total},
                    recommended_action="collect_more_execution_coverage",
                )
            )
        elif fill_events_total <= 0:
            reasons.append(
                self._reason(
                    code="execution_fills_missing",
                    severity="watch",
                    message="execution fills are missing, so quality signals rely mostly on fallback-derived coverage",
                    evidence={"plans_matured": matured_plans, "fill_events_total": fill_events_total},
                    recommended_action="restore_fill_ingestion_before_scaling",
                )
            )

        worst_entry_model_fill = dict(dict(performance_payload.get("entry_model") or {}).get("worst_fill_rate") or {})
        if matured_plans >= self._MIN_MATURED_FOR_FILL_MANUAL and fill_rate <= self._FILL_RATE_MANUAL:
            reasons.append(
                self._reason(
                    code="fill_rate_subscale",
                    severity="manual_review",
                    message="fill rate is materially below tolerance for recent matured plans",
                    evidence={
                        "fill_rate": round(fill_rate, 4),
                        "plans_matured": matured_plans,
                        "worst_entry_model": worst_entry_model_fill.get("name"),
                        "worst_entry_model_fill_rate": worst_entry_model_fill.get("fill_rate"),
                    },
                    recommended_action="review_submit_path_and_entry_model_fill",
                )
            )
        elif matured_plans >= self._MIN_MATURED_FOR_FILL_WATCH and fill_rate <= self._FILL_RATE_WATCH:
            reasons.append(
                self._reason(
                    code="fill_rate_drift",
                    severity="watch",
                    message="fill rate is drifting below the normal operating range",
                    evidence={
                        "fill_rate": round(fill_rate, 4),
                        "plans_matured": matured_plans,
                        "worst_entry_model": worst_entry_model_fill.get("name"),
                        "worst_entry_model_fill_rate": worst_entry_model_fill.get("fill_rate"),
                    },
                    recommended_action="review_submit_path_and_entry_model_fill",
                )
            )

        worst_slippage_model = dict(dict(performance_payload.get("entry_model") or {}).get("worst_slippage_bps") or {})
        if slippage_p95 >= float(slippage_thresholds["manual_review_slippage_p95_bps"]):
            reasons.append(
                self._reason(
                    code="slippage_p95_exceeds_live_tolerance",
                    severity="manual_review",
                    message="p95 entry slippage exceeds the current live-tolerance threshold",
                    evidence={
                        "slippage_p95_bps": round(slippage_p95, 4),
                        "threshold_bps": slippage_thresholds["manual_review_slippage_p95_bps"],
                        "worst_entry_model": worst_slippage_model.get("name"),
                        "worst_entry_model_slippage_bps": worst_slippage_model.get("avg_slippage_bps"),
                    },
                    recommended_action="review_entry_cost_drag_before_new_live_entries",
                )
            )
        elif slippage_p95 >= float(slippage_thresholds["watch_slippage_p95_bps"]):
            reasons.append(
                self._reason(
                    code="slippage_p95_drift",
                    severity="watch",
                    message="p95 entry slippage is drifting toward the configured live-tolerance threshold",
                    evidence={
                        "slippage_p95_bps": round(slippage_p95, 4),
                        "threshold_bps": slippage_thresholds["watch_slippage_p95_bps"],
                        "worst_entry_model": worst_slippage_model.get("name"),
                        "worst_entry_model_slippage_bps": worst_slippage_model.get("avg_slippage_bps"),
                    },
                    recommended_action="review_entry_cost_drag_before_new_live_entries",
                )
            )

        family_summary = dict(performance_payload.get("family") or {})
        highest_forced_family = dict(family_summary.get("highest_forced_exit_rate") or {})
        if closed_plans >= self._MIN_CLOSED_FOR_FAILURE_MANUAL and forced_exit_ratio >= self._FORCED_EXIT_MANUAL:
            reasons.append(
                self._reason(
                    code="forced_exit_ratio_elevated",
                    severity="manual_review",
                    message="forced exits are elevated enough to question current execution stability",
                    evidence={
                        "forced_exit_ratio": round(forced_exit_ratio, 4),
                        "closed_plans": closed_plans,
                        "highest_forced_exit_family": highest_forced_family.get("name"),
                        "highest_forced_exit_family_rate": highest_forced_family.get("forced_exit_rate"),
                    },
                    recommended_action="review_exit_timing_and_forced_exit_mix",
                )
            )
        elif closed_plans >= self._MIN_CLOSED_FOR_FAILURE_WATCH and forced_exit_ratio >= self._FORCED_EXIT_WATCH:
            reasons.append(
                self._reason(
                    code="forced_exit_ratio_drift",
                    severity="watch",
                    message="forced exits are rising and should be reviewed before expanding risk",
                    evidence={
                        "forced_exit_ratio": round(forced_exit_ratio, 4),
                        "closed_plans": closed_plans,
                        "highest_forced_exit_family": highest_forced_family.get("name"),
                        "highest_forced_exit_family_rate": highest_forced_family.get("forced_exit_rate"),
                    },
                    recommended_action="review_exit_timing_and_forced_exit_mix",
                )
            )

        highest_info_family = dict(family_summary.get("highest_information_failure_rate") or {})
        if closed_plans >= self._MIN_CLOSED_FOR_FAILURE_MANUAL and information_failure_ratio >= self._INFO_FAILURE_MANUAL:
            reasons.append(
                self._reason(
                    code="information_failure_ratio_elevated",
                    severity="manual_review",
                    message="information failures are elevated enough to require manual execution review",
                    evidence={
                        "information_failure_ratio": round(information_failure_ratio, 4),
                        "closed_plans": closed_plans,
                        "highest_information_failure_family": highest_info_family.get("name"),
                        "highest_information_failure_family_rate": highest_info_family.get("information_failure_rate"),
                    },
                    recommended_action="review_information_failure_and_candidate_quality",
                )
            )
        elif closed_plans >= self._MIN_CLOSED_FOR_FAILURE_WATCH and information_failure_ratio >= self._INFO_FAILURE_WATCH:
            reasons.append(
                self._reason(
                    code="information_failure_ratio_drift",
                    severity="watch",
                    message="information failures are rising and should be reviewed before scaling",
                    evidence={
                        "information_failure_ratio": round(information_failure_ratio, 4),
                        "closed_plans": closed_plans,
                        "highest_information_failure_family": highest_info_family.get("name"),
                        "highest_information_failure_family_rate": highest_info_family.get("information_failure_rate"),
                    },
                    recommended_action="review_information_failure_and_candidate_quality",
                )
            )

        highest_time_family = dict(family_summary.get("highest_time_failure_rate") or {})
        if closed_plans >= self._MIN_CLOSED_FOR_FAILURE_MANUAL and time_failure_ratio >= self._TIME_FAILURE_MANUAL:
            reasons.append(
                self._reason(
                    code="time_failure_ratio_elevated",
                    severity="manual_review",
                    message="time failures are elevated enough to require manual exit-timing review",
                    evidence={
                        "time_failure_ratio": round(time_failure_ratio, 4),
                        "closed_plans": closed_plans,
                        "highest_time_failure_family": highest_time_family.get("name"),
                        "highest_time_failure_family_rate": highest_time_family.get("time_failure_rate"),
                    },
                    recommended_action="review_time_failure_and_hold_window",
                )
            )
        elif closed_plans >= self._MIN_CLOSED_FOR_FAILURE_WATCH and time_failure_ratio >= self._TIME_FAILURE_WATCH:
            reasons.append(
                self._reason(
                    code="time_failure_ratio_drift",
                    severity="watch",
                    message="time failures are drifting upward and should be reviewed",
                    evidence={
                        "time_failure_ratio": round(time_failure_ratio, 4),
                        "closed_plans": closed_plans,
                        "highest_time_failure_family": highest_time_family.get("name"),
                        "highest_time_failure_family_rate": highest_time_family.get("time_failure_rate"),
                    },
                    recommended_action="review_time_failure_and_hold_window",
                )
            )

        stress_recommendation = dict(stress_payload.get("deployment_recommendation") or {})
        stress_pass = bool(stress_recommendation.get("stress_pass", False))
        stress_reason = str(stress_recommendation.get("reason", "") or "")
        perf_cost = dict(performance_payload.get("cost") or {})
        stressed_cost_ev = float(perf_cost.get("stressed_cost_ev", 0.0) or 0.0)
        delta_cost_ev = float(perf_cost.get("delta_ev_stressed_minus_baseline", 0.0) or 0.0)

        if stress_payload and not stress_pass:
            reasons.append(
                self._reason(
                    code="stress_cost_degraded",
                    severity="manual_review",
                    message="stress validation does not currently support expansion under the cost-adjusted scenario mix",
                    evidence={
                        "stress_pass": stress_pass,
                        "stress_reason": stress_reason,
                        "stressed_cost_ev": round(stressed_cost_ev, 4),
                        "delta_ev_stressed_minus_baseline": round(delta_cost_ev, 4),
                        "worst_scenario": stress_recommendation.get("worst_scenario"),
                    },
                    recommended_action="hold_expansion_and_review_stress_drag",
                )
            )
        elif stress_payload and delta_cost_ev < 0.0:
            reasons.append(
                self._reason(
                    code="post_cost_ev_deterioration",
                    severity="watch",
                    message="post-cost EV deteriorates under the baseline stress approximation",
                    evidence={
                        "stressed_cost_ev": round(stressed_cost_ev, 4),
                        "delta_ev_stressed_minus_baseline": round(delta_cost_ev, 4),
                        "worst_scenario": stress_recommendation.get("worst_scenario"),
                    },
                    recommended_action="review_cost_drag_before_scaling",
                )
            )

        reasons.sort(
            key=lambda item: (
                -self._severity_rank(str(item.get("severity") or "healthy")),
                str(item.get("code") or ""),
            )
        )
        status = self._overall_status(reasons)
        return {
            "available": True,
            "status": status,
            "healthy": status == "healthy",
            "summary": self._summary_for_status(status),
            "recommended_action": self._recommended_action_for_status(status),
            "reason_codes": [str(item.get("code") or "") for item in reasons],
            "reasons": reasons,
            "thresholds": {
                **slippage_thresholds,
                "watch_fill_rate": self._FILL_RATE_WATCH,
                "manual_review_fill_rate": self._FILL_RATE_MANUAL,
                "watch_forced_exit_ratio": self._FORCED_EXIT_WATCH,
                "manual_review_forced_exit_ratio": self._FORCED_EXIT_MANUAL,
                "watch_information_failure_ratio": self._INFO_FAILURE_WATCH,
                "manual_review_information_failure_ratio": self._INFO_FAILURE_MANUAL,
                "watch_time_failure_ratio": self._TIME_FAILURE_WATCH,
                "manual_review_time_failure_ratio": self._TIME_FAILURE_MANUAL,
            },
            "sample_context": {
                "plans_matured": matured_plans,
                "fill_events_total": fill_events_total,
                "closed_plans": closed_plans,
            },
            "advisory_only": True,
        }
