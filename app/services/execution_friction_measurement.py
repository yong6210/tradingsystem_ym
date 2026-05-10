from __future__ import annotations

from typing import Any


class ExecutionFrictionMeasurementService:
    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

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
    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    @classmethod
    def _measurement_coverage_state(cls, *, fills_matched: int, execution_fill_coverage: float) -> str:
        if fills_matched < 4 or execution_fill_coverage < 0.50:
            return "thin_measurement"
        if fills_matched < 8 or execution_fill_coverage < 0.70:
            return "partial_measurement"
        return "mature_measurement"

    @classmethod
    def _fill_conversion_state(
        cls,
        *,
        fill_rate: float,
        information_failure_ratio: float,
        time_failure_ratio: float,
    ) -> str:
        if fill_rate < 0.30 or information_failure_ratio >= 0.25 or time_failure_ratio >= 0.35:
            return "degraded_fill_conversion"
        if fill_rate < 0.50 or information_failure_ratio >= 0.15 or time_failure_ratio >= 0.20:
            return "watch_fill_conversion"
        return "healthy_fill_conversion"

    @classmethod
    def _slippage_state(
        cls,
        *,
        avg_slippage_bps: float,
        p95_slippage_bps: float,
        approval_slippage_cap_bps: float,
    ) -> str:
        if (
            p95_slippage_bps >= approval_slippage_cap_bps
            or avg_slippage_bps >= approval_slippage_cap_bps * 0.75
        ):
            return "degraded_slippage"
        if (
            p95_slippage_bps >= approval_slippage_cap_bps * 0.50
            or avg_slippage_bps >= approval_slippage_cap_bps * 0.50
        ):
            return "watch_slippage"
        return "healthy_slippage"

    @classmethod
    def _latency_state(
        cls,
        *,
        p95_entry_latency_seconds: float,
        p95_latency_penalty_r: float,
    ) -> str:
        if p95_latency_penalty_r >= 0.20 or p95_entry_latency_seconds >= 1800:
            return "degraded_latency"
        if p95_latency_penalty_r >= 0.10 or p95_entry_latency_seconds >= 900:
            return "watch_latency"
        return "healthy_latency"

    @classmethod
    def _fee_state(
        cls,
        *,
        avg_fee_component_r: float,
        p95_fee_component_r: float,
    ) -> str:
        if p95_fee_component_r >= 0.20 or avg_fee_component_r >= 0.10:
            return "degraded_fee_drag"
        if p95_fee_component_r >= 0.10 or avg_fee_component_r >= 0.05:
            return "watch_fee_drag"
        return "healthy_fee_drag"

    @classmethod
    def _reconciliation_state(cls, *, reconciliation_summary: dict[str, Any]) -> str:
        summary = dict(reconciliation_summary or {})
        highest_severity = str(summary.get("highest_severity") or "INFO").upper()
        critical_count = cls._int(summary.get("critical_count", 0))
        lock_required_count = cls._int(summary.get("lock_required_count", 0))
        degraded = cls._safe_bool(summary.get("degraded", False))
        if highest_severity == "CRITICAL" or critical_count > 0 or lock_required_count > 0:
            return "degraded_reconciliation"
        if degraded or highest_severity == "WARNING":
            return "watch_reconciliation"
        return "healthy_reconciliation"

    @classmethod
    def _stress_drag_state(cls, *, strategy_v2_stress_validation: dict[str, Any]) -> str:
        payload = dict(strategy_v2_stress_validation or {})
        if not payload or not cls._safe_bool(payload.get("available", False)):
            return "unknown_stress_drag"

        recommendation = dict(payload.get("deployment_recommendation") or {})
        comparison = dict(payload.get("comparison") or {})
        reason_text = " ".join(
            [
                str(recommendation.get("reason") or ""),
                str(recommendation.get("replay_gate_reason") or ""),
                str(recommendation.get("worst_scenario") or ""),
            ]
        ).lower()
        stress_pass = cls._safe_bool(recommendation.get("stress_pass", False))
        replay_gate_applied = cls._safe_bool(recommendation.get("replay_gate_applied", False))
        divergence_gate_applied = cls._safe_bool(recommendation.get("divergence_gate_applied", False))

        if (not stress_pass) or any(
            token in reason_text for token in ("reduce", "research_only", "hold", "manual", "defer")
        ):
            return "degraded_stress_drag"
        if (
            replay_gate_applied
            or divergence_gate_applied
            or cls._float(comparison.get("ev", 0.0)) < 0.0
            or cls._float(comparison.get("p5_ev", 0.0)) < 0.0
        ):
            return "watch_stress_drag"
        return "healthy_stress_drag"

    @classmethod
    def _friction_state(
        cls,
        *,
        measurement_coverage_state: str,
        fill_conversion_state: str,
        slippage_state: str,
        latency_state: str,
        fee_state: str,
        reconciliation_state: str,
        stress_drag_state: str,
    ) -> str:
        if measurement_coverage_state == "thin_measurement":
            return "insufficient_measurement"

        watch_or_worse_count = sum(
            1
            for value in (
                fill_conversion_state,
                slippage_state,
                latency_state,
                fee_state,
                reconciliation_state,
            )
            if value.startswith("watch_") or value.startswith("degraded_")
        )

        if (
            reconciliation_state == "degraded_reconciliation"
            or slippage_state == "degraded_slippage"
            or latency_state == "degraded_latency"
            or fee_state == "degraded_fee_drag"
            or fill_conversion_state == "degraded_fill_conversion"
            or watch_or_worse_count >= 3
            or (
                stress_drag_state == "degraded_stress_drag"
                and (
                    slippage_state == "watch_slippage"
                    or latency_state == "watch_latency"
                    or fill_conversion_state == "watch_fill_conversion"
                )
            )
        ):
            return "degraded_friction"

        if (
            measurement_coverage_state == "partial_measurement"
            or reconciliation_state == "watch_reconciliation"
            or slippage_state == "watch_slippage"
            or latency_state == "watch_latency"
            or fee_state == "watch_fee_drag"
            or fill_conversion_state == "watch_fill_conversion"
            or stress_drag_state == "watch_stress_drag"
        ):
            return "watch_friction"

        return "healthy_friction"

    @classmethod
    def _friction_bias(cls, friction_state: str) -> str:
        return {
            "healthy_friction": "keep_execution_confidence",
            "watch_friction": "monitor_execution_drag",
            "degraded_friction": "reduce_execution_confidence",
            "insufficient_measurement": "gather_more_execution_evidence",
        }.get(friction_state, "gather_more_execution_evidence")

    @classmethod
    def _weakest_axis(
        cls,
        *,
        fill_conversion_state: str,
        slippage_state: str,
        latency_state: str,
        fee_state: str,
        reconciliation_state: str,
        measurement_coverage_state: str,
    ) -> str:
        priority = (
            ("reconciliation_state", reconciliation_state),
            ("slippage_state", slippage_state),
            ("latency_state", latency_state),
            ("fill_conversion_state", fill_conversion_state),
            ("fee_state", fee_state),
            ("measurement_coverage_state", measurement_coverage_state),
        )
        for axis, value in priority:
            if value.startswith("degraded_") or value.startswith("watch_") or value == "partial_measurement":
                return axis
        return ""

    @classmethod
    def _confidence(
        cls,
        *,
        measurement_coverage_state: str,
        execution_fill_coverage: float,
        reconciliation_state: str,
        stress_drag_state: str,
    ) -> str:
        if measurement_coverage_state == "thin_measurement" or stress_drag_state == "unknown_stress_drag":
            return "low"
        if (
            measurement_coverage_state == "partial_measurement"
            or execution_fill_coverage < 0.85
            or reconciliation_state != "healthy_reconciliation"
        ):
            return "medium"
        return "high"

    @classmethod
    def _summary(
        cls,
        *,
        friction_state: str,
        weakest_axis: str,
        fill_rate: float,
        avg_slippage_bps: float,
        p95_slippage_bps: float,
    ) -> str:
        if friction_state == "healthy_friction":
            return (
                "Measured execution friction remains within current operating tolerance. "
                f"fill_rate={fill_rate:.4f}, avg_slippage_bps={avg_slippage_bps:.4f}, "
                f"p95_slippage_bps={p95_slippage_bps:.4f}."
            )
        if friction_state == "watch_friction":
            if weakest_axis == "slippage_state":
                return "Execution drag is still manageable, but slippage is softening current post-cost confidence."
            if weakest_axis == "latency_state":
                return "Execution drag is still manageable, but latency pressure is rising enough to warrant monitoring."
            if weakest_axis == "fill_conversion_state":
                return "Execution drag is still manageable, but fill conversion is weakening and needs monitoring."
            if weakest_axis == "reconciliation_state":
                return "Execution integrity is still usable, but reconciliation noise is high enough to monitor closely."
            if weakest_axis == "measurement_coverage_state":
                return "Execution drag evidence is only partially measured; keep current conclusions guarded."
            return "Execution drag is still manageable but needs monitoring before trusting current post-cost assumptions."
        if friction_state == "degraded_friction":
            if weakest_axis == "reconciliation_state":
                return "Measured execution integrity is materially degraded by reconciliation mismatch and should be treated as a real drag source."
            if weakest_axis == "slippage_state":
                return "Measured execution friction is materially degraded by slippage and should be treated as a real drag source."
            if weakest_axis == "latency_state":
                return "Measured execution friction is materially degraded by latency and should be treated as a real drag source."
            if weakest_axis == "fill_conversion_state":
                return "Measured execution friction is materially degraded by weak fill conversion and should be treated as a real drag source."
            if weakest_axis == "fee_state":
                return "Measured execution friction is materially degraded by fee drag and should be treated as a real drag source."
            return "Measured execution friction is materially weakening live confidence and should be treated as a real drag source."
        return "Current fill-ledger coverage is too thin to treat execution friction as measured and stable."

    @classmethod
    def generate(
        cls,
        *,
        execution_quality: dict[str, Any] | None,
        recent_reconciliation_summary: dict[str, Any] | None,
        strategy_v2_stress_validation: dict[str, Any] | None,
        approval_caps: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        execution_quality_payload = cls._dict(execution_quality)
        if not execution_quality_payload:
            return None

        reconciliation_payload = cls._dict(recent_reconciliation_summary)
        stress_payload = cls._dict(strategy_v2_stress_validation)
        approval_caps_payload = cls._dict(approval_caps)

        fill_sources = cls._dict(execution_quality_payload.get("fill_sources"))
        slippage_payload = cls._dict(execution_quality_payload.get("slippage_bps"))
        latency_payload = cls._dict(execution_quality_payload.get("entry_latency_seconds"))
        stress_cost_summary = cls._dict(stress_payload.get("cost_summary"))
        fee_component_payload = cls._dict(stress_cost_summary.get("fee_component_r"))
        stress_scenario_summary = cls._dict(stress_payload.get("scenario_summary"))
        latency_penalty_payload = cls._dict(stress_scenario_summary.get("latency_penalty_r"))

        fills_matched = cls._int(execution_quality_payload.get("fills_matched", 0))
        fill_events_total = cls._int(execution_quality_payload.get("fill_events_total", 0))
        fill_rate = cls._float(execution_quality_payload.get("fill_rate", 0.0))
        execution_fill_count = cls._int(fill_sources.get("execution_fills", 0))
        execution_fill_coverage = float(execution_fill_count / fills_matched) if fills_matched > 0 else 0.0
        information_failure_ratio = cls._float(execution_quality_payload.get("information_failure_ratio", 0.0))
        time_failure_ratio = cls._float(execution_quality_payload.get("time_failure_ratio", 0.0))
        avg_slippage_bps = cls._float(slippage_payload.get("avg", 0.0))
        p95_slippage_bps = cls._float(slippage_payload.get("p95", 0.0))
        avg_entry_latency_seconds = cls._float(latency_payload.get("avg", 0.0))
        p95_entry_latency_seconds = cls._float(latency_payload.get("p95", 0.0))
        avg_fee_component_r = cls._float(fee_component_payload.get("avg", 0.0))
        p95_fee_component_r = cls._float(fee_component_payload.get("p95", 0.0))
        p95_latency_penalty_r = cls._float(latency_penalty_payload.get("p95", 0.0))
        approval_slippage_cap_bps = cls._float(approval_caps_payload.get("max_slippage_bps", 12.0), 12.0)
        approval_fee_bps_reference = cls._float(approval_caps_payload.get("expected_fee_bps", 4.0), 4.0)

        measurement_coverage_state = cls._measurement_coverage_state(
            fills_matched=fills_matched,
            execution_fill_coverage=execution_fill_coverage,
        )
        fill_conversion_state = cls._fill_conversion_state(
            fill_rate=fill_rate,
            information_failure_ratio=information_failure_ratio,
            time_failure_ratio=time_failure_ratio,
        )
        slippage_state = cls._slippage_state(
            avg_slippage_bps=avg_slippage_bps,
            p95_slippage_bps=p95_slippage_bps,
            approval_slippage_cap_bps=approval_slippage_cap_bps,
        )
        latency_state = cls._latency_state(
            p95_entry_latency_seconds=p95_entry_latency_seconds,
            p95_latency_penalty_r=p95_latency_penalty_r,
        )
        fee_state = cls._fee_state(
            avg_fee_component_r=avg_fee_component_r,
            p95_fee_component_r=p95_fee_component_r,
        )
        reconciliation_state = cls._reconciliation_state(reconciliation_summary=reconciliation_payload)
        stress_drag_state = cls._stress_drag_state(strategy_v2_stress_validation=stress_payload)
        friction_state = cls._friction_state(
            measurement_coverage_state=measurement_coverage_state,
            fill_conversion_state=fill_conversion_state,
            slippage_state=slippage_state,
            latency_state=latency_state,
            fee_state=fee_state,
            reconciliation_state=reconciliation_state,
            stress_drag_state=stress_drag_state,
        )
        friction_bias = cls._friction_bias(friction_state)
        weakest_axis = cls._weakest_axis(
            fill_conversion_state=fill_conversion_state,
            slippage_state=slippage_state,
            latency_state=latency_state,
            fee_state=fee_state,
            reconciliation_state=reconciliation_state,
            measurement_coverage_state=measurement_coverage_state,
        )
        confidence = cls._confidence(
            measurement_coverage_state=measurement_coverage_state,
            execution_fill_coverage=execution_fill_coverage,
            reconciliation_state=reconciliation_state,
            stress_drag_state=stress_drag_state,
        )
        reason_codes = cls._dedupe(
            [
                f"coverage:{measurement_coverage_state}",
                f"fill_conversion:{fill_conversion_state}",
                f"slippage:{slippage_state}",
                f"latency:{latency_state}",
                f"fee:{fee_state}",
                f"reconciliation:{reconciliation_state}",
                f"stress:{stress_drag_state}",
            ]
        )

        return {
            "available": True,
            "advisory_only": True,
            "friction_state": friction_state,
            "friction_bias": friction_bias,
            "fill_conversion_state": fill_conversion_state,
            "slippage_state": slippage_state,
            "latency_state": latency_state,
            "fee_state": fee_state,
            "reconciliation_state": reconciliation_state,
            "measurement_coverage_state": measurement_coverage_state,
            "stress_drag_state": stress_drag_state,
            "fill_rate": fill_rate,
            "fills_matched": fills_matched,
            "fill_events_total": fill_events_total,
            "execution_fill_coverage": execution_fill_coverage,
            "avg_slippage_bps": avg_slippage_bps,
            "p95_slippage_bps": p95_slippage_bps,
            "avg_entry_latency_seconds": avg_entry_latency_seconds,
            "p95_entry_latency_seconds": p95_entry_latency_seconds,
            "avg_fee_component_r": avg_fee_component_r,
            "p95_fee_component_r": p95_fee_component_r,
            "approval_slippage_cap_bps": approval_slippage_cap_bps,
            "approval_fee_bps_reference": approval_fee_bps_reference,
            "weakest_axis": weakest_axis,
            "confidence": confidence,
            "summary": cls._summary(
                friction_state=friction_state,
                weakest_axis=weakest_axis,
                fill_rate=fill_rate,
                avg_slippage_bps=avg_slippage_bps,
                p95_slippage_bps=p95_slippage_bps,
            ),
            "reason_codes": reason_codes,
            "source_summary": {
                "execution_quality_report_path": execution_quality_payload.get("report_path"),
                "stress_validation_report_path": stress_payload.get("report_path"),
                "stress_available": cls._safe_bool(stress_payload.get("available", False)),
                "fill_sources": fill_sources,
                "reconciliation_highest_severity": str(reconciliation_payload.get("highest_severity") or "INFO"),
                "approval_slippage_cap_bps": approval_slippage_cap_bps,
                "approval_fee_bps_reference": approval_fee_bps_reference,
            },
        }
