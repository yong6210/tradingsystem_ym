from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.services.execution_degradation_advisory import ExecutionDegradationAdvisoryService


class FamilyExecutionDegradationAdvisoryService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.global_advisory = ExecutionDegradationAdvisoryService(self.settings)

    @staticmethod
    def _confidence_from_samples(samples: int) -> str:
        if samples >= 8:
            return "high"
        if samples >= 4:
            return "medium"
        return "low"

    @classmethod
    def _sample_note(cls, samples: int) -> str:
        confidence = cls._confidence_from_samples(samples)
        if confidence == "high":
            return "family closed sample is sufficient for advisory use"
        if confidence == "medium":
            return "family sample is usable, but still limited"
        return "family sample is thin; treat this as advisory context only"

    @staticmethod
    def _severity_rank(value: str) -> int:
        return {"healthy": 0, "watch": 1, "manual_review": 2}.get(str(value or "healthy"), 0)

    @staticmethod
    def _reason(
        *,
        code: str,
        severity: str,
        message: str,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "message": message,
        }

    def _post_cost_alignment(
        self,
        *,
        family: str,
        family_summary: dict[str, Any],
        funnel_row: dict[str, Any],
    ) -> str:
        worst_ev_family = str(dict(family_summary.get("worst_ev") or {}).get("name") or "")
        highest_forced_family = str(dict(family_summary.get("highest_forced_exit_rate") or {}).get("name") or "")
        highest_info_family = str(dict(family_summary.get("highest_information_failure_rate") or {}).get("name") or "")
        closed = int(funnel_row.get("closed", 0) or 0)
        baseline_cost_profitable_rate = float(funnel_row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)

        if closed < 3:
            return "not_enough_evidence"
        if family in {worst_ev_family, highest_forced_family, highest_info_family} and baseline_cost_profitable_rate <= 0.3:
            return "aligned_negative"
        if baseline_cost_profitable_rate >= 0.5:
            return "stable"
        return "mixed"

    @staticmethod
    def _status_summary(status: str) -> str:
        if status == "manual_review":
            return "family execution drag requires manual review before expanding this family"
        if status == "watch":
            return "family execution quality is drifting and should be reviewed before scaling"
        return "family execution quality is within current advisory tolerance"

    @staticmethod
    def _recommended_action(status: str) -> str:
        if status == "manual_review":
            return "review_family_execution_drag_before_expansion"
        if status == "watch":
            return "monitor_family_execution_drag_and_hold_size"
        return "continue_family_runtime_monitoring"

    def generate(
        self,
        *,
        execution_quality: dict[str, Any] | None,
        performance_decomposition_summary: dict[str, Any] | None,
        score_to_outcome_funnel: dict[str, Any] | None,
    ) -> dict[str, Any]:
        execution_payload = dict(execution_quality or {})
        performance_payload = dict(performance_decomposition_summary or {})
        funnel_payload = dict(score_to_outcome_funnel or {})

        family_execution = dict(execution_payload.get("by_strategy_family") or {})
        family_summary = dict(performance_payload.get("family") or {})
        family_funnel_rows = {
            str(item.get("key") or "unknown"): dict(item)
            for item in list(dict(funnel_payload.get("decomposition") or {}).get("family") or [])
        }

        families = sorted(
            {
                *family_execution.keys(),
                *family_funnel_rows.keys(),
                str(dict(family_summary.get("worst_ev") or {}).get("name") or ""),
                str(dict(family_summary.get("highest_forced_exit_rate") or {}).get("name") or ""),
                str(dict(family_summary.get("highest_information_failure_rate") or {}).get("name") or ""),
            }
            - {""}
        )

        if not families:
            return {
                "available": False,
                "coverage_note": (
                    "family execution advisory unavailable; no family execution or funnel decomposition coverage is present"
                ),
                "families": [],
            }

        rows: list[dict[str, Any]] = []
        for family in families:
            exec_row = dict(family_execution.get(family) or {})
            funnel_row = dict(family_funnel_rows.get(family) or {})

            closed = max(int(exec_row.get("closed", 0) or 0), int(funnel_row.get("closed", 0) or 0))
            submitted = int(funnel_row.get("submitted", 0) or 0)
            filled = max(int(exec_row.get("filled", 0) or 0), int(funnel_row.get("filled", 0) or 0))
            samples = max(closed, submitted, filled)
            confidence = self._confidence_from_samples(samples)
            sample_note = self._sample_note(samples)

            fill_rate = (
                float(funnel_row.get("fill_rate_from_submitted", 0.0) or 0.0)
                if submitted > 0
                else None
            )
            forced_exit_ratio = float(exec_row.get("forced_exit_rate", 0.0) or 0.0)
            information_failure_ratio = float(exec_row.get("information_failure_rate", 0.0) or 0.0)
            time_failure_ratio = float(exec_row.get("time_failure_rate", 0.0) or 0.0)
            avg_slippage_bps = None

            reasons: list[dict[str, Any]] = []
            if submitted >= self.global_advisory._MIN_MATURED_FOR_FILL_MANUAL and fill_rate is not None:
                if fill_rate <= self.global_advisory._FILL_RATE_MANUAL:
                    reasons.append(
                        self._reason(
                            code="family_fill_rate_subscale",
                            severity="manual_review",
                            message="family fill rate is materially below tolerance",
                        )
                    )
                elif fill_rate <= self.global_advisory._FILL_RATE_WATCH:
                    reasons.append(
                        self._reason(
                            code="family_fill_rate_drift",
                            severity="watch",
                            message="family fill rate is drifting below the normal operating range",
                        )
                    )

            if closed >= self.global_advisory._MIN_CLOSED_FOR_FAILURE_MANUAL:
                if forced_exit_ratio >= self.global_advisory._FORCED_EXIT_MANUAL:
                    reasons.append(
                        self._reason(
                            code="family_forced_exit_ratio_elevated",
                            severity="manual_review",
                            message="family forced exits are elevated enough to require manual review",
                        )
                    )
                elif forced_exit_ratio >= self.global_advisory._FORCED_EXIT_WATCH:
                    reasons.append(
                        self._reason(
                            code="family_forced_exit_ratio_drift",
                            severity="watch",
                            message="family forced exits are rising and should be reviewed",
                        )
                    )
                if information_failure_ratio >= self.global_advisory._INFO_FAILURE_MANUAL:
                    reasons.append(
                        self._reason(
                            code="family_information_failure_elevated",
                            severity="manual_review",
                            message="family information failures are elevated enough to require manual review",
                        )
                    )
                elif information_failure_ratio >= self.global_advisory._INFO_FAILURE_WATCH:
                    reasons.append(
                        self._reason(
                            code="family_information_failure_drift",
                            severity="watch",
                            message="family information failures are drifting above the normal range",
                        )
                    )
                if time_failure_ratio >= self.global_advisory._TIME_FAILURE_MANUAL:
                    reasons.append(
                        self._reason(
                            code="family_time_failure_elevated",
                            severity="manual_review",
                            message="family time failures are elevated enough to require manual review",
                        )
                    )
                elif time_failure_ratio >= self.global_advisory._TIME_FAILURE_WATCH:
                    reasons.append(
                        self._reason(
                            code="family_time_failure_drift",
                            severity="watch",
                            message="family time failures are drifting above the normal range",
                        )
                    )
            elif closed >= self.global_advisory._MIN_CLOSED_FOR_FAILURE_WATCH:
                if forced_exit_ratio >= self.global_advisory._FORCED_EXIT_WATCH:
                    reasons.append(
                        self._reason(
                            code="family_forced_exit_ratio_drift",
                            severity="watch",
                            message="family forced exits are rising and should be reviewed",
                        )
                    )
                if information_failure_ratio >= self.global_advisory._INFO_FAILURE_WATCH:
                    reasons.append(
                        self._reason(
                            code="family_information_failure_drift",
                            severity="watch",
                            message="family information failures are drifting above the normal range",
                        )
                    )
                if time_failure_ratio >= self.global_advisory._TIME_FAILURE_WATCH:
                    reasons.append(
                        self._reason(
                            code="family_time_failure_drift",
                            severity="watch",
                            message="family time failures are drifting above the normal range",
                        )
                    )

            post_cost_alignment = self._post_cost_alignment(
                family=family,
                family_summary=family_summary,
                funnel_row=funnel_row,
            )
            if post_cost_alignment == "aligned_negative" and closed >= 4:
                reasons.append(
                    self._reason(
                        code="family_post_cost_alignment_negative",
                        severity="watch",
                        message="family execution drag aligns with weak post-cost outcome conversion",
                    )
                )

            status = "healthy"
            if reasons:
                status = max(
                    (str(item.get("severity") or "healthy") for item in reasons),
                    key=self._severity_rank,
                )

            rows.append(
                {
                    "family": family,
                    "status": status,
                    "summary": self._status_summary(status),
                    "reason_codes": [str(item.get("code") or "") for item in reasons if item.get("code")],
                    "recommended_action": self._recommended_action(status),
                    "fill_rate": round(fill_rate, 4) if isinstance(fill_rate, float) else None,
                    "avg_slippage_bps": avg_slippage_bps,
                    "forced_exit_ratio": round(forced_exit_ratio, 4),
                    "information_failure_ratio": round(information_failure_ratio, 4),
                    "time_failure_ratio": round(time_failure_ratio, 4),
                    "post_cost_alignment": post_cost_alignment,
                    "confidence": confidence,
                    "sample_note": sample_note,
                    "advisory_only": True,
                }
            )

        rows.sort(
            key=lambda item: (
                -self._severity_rank(item.get("status")),
                {"high": 2, "medium": 1, "low": 0}.get(str(item.get("confidence") or "low"), 0) * -1,
                -float(item.get("forced_exit_ratio", 0.0) or 0.0),
                str(item.get("family") or ""),
            )
        )

        return {
            "available": True,
            "coverage_note": (
                "family execution advisory is advisory-only; fill-rate comes from family funnel history, "
                "failure ratios come from execution_quality.by_strategy_family, and avg_slippage_bps is unavailable "
                "because family-level slippage is not currently emitted as a primary metric"
            ),
            "families": rows,
        }
