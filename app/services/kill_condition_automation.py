from __future__ import annotations

from typing import Any


class KillConditionAutomationService:
    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    @staticmethod
    def _normalize_risk_gate_state(strategy_metrics: dict[str, Any]) -> str:
        state = str(strategy_metrics.get("risk_state") or "").upper()
        if state == "OPEN":
            return "open"
        if state == "THROTTLED":
            return "throttled"
        if state == "CLOSED":
            return "closed"
        return "unknown"

    @staticmethod
    def _normalize_friction_state(execution_friction_measurement: dict[str, Any]) -> str:
        state = str(execution_friction_measurement.get("friction_state") or "")
        return {
            "healthy_friction": "healthy",
            "watch_friction": "watch",
            "degraded_friction": "degraded",
            "insufficient_measurement": "insufficient",
        }.get(state, "unknown")

    @staticmethod
    def _normalize_generalization_state(forward_stress_regime_validation: dict[str, Any]) -> str:
        state = str(forward_stress_regime_validation.get("validation_state") or "")
        return {
            "validated_generalization": "validated",
            "fragile_generalization": "fragile",
            "insufficient_generalization": "insufficient",
            "insufficient_evidence": "insufficient_evidence",
        }.get(state, "unknown")

    @staticmethod
    def _normalize_reconciliation_state(recent_reconciliation_summary: dict[str, Any]) -> str:
        if not recent_reconciliation_summary:
            return "unknown"
        highest_severity = str(recent_reconciliation_summary.get("highest_severity") or "INFO").upper()
        critical_count = int(recent_reconciliation_summary.get("critical_count", 0) or 0)
        lock_required_count = int(recent_reconciliation_summary.get("lock_required_count", 0) or 0)
        degraded = bool(recent_reconciliation_summary.get("degraded", False))
        if highest_severity == "CRITICAL" or critical_count > 0 or lock_required_count > 0:
            return "critical"
        if degraded or highest_severity in {"WARNING", "WARN", "ERROR"}:
            return "degraded"
        return "healthy"

    @staticmethod
    def _normalize_execution_degradation_state(execution_degradation_advisory: dict[str, Any]) -> str:
        state = str(execution_degradation_advisory.get("status") or "")
        if state in {"healthy", "watch", "manual_review"}:
            return state
        return "unknown"

    @staticmethod
    def _normalize_family_execution_state(family_execution_degradation_advisory: dict[str, Any]) -> str:
        top_family = dict(family_execution_degradation_advisory.get("top_family") or {})
        state = str(top_family.get("status") or "")
        if state in {"healthy", "watch", "manual_review"}:
            return state
        return "unknown"

    @staticmethod
    def _manual_override_reason(safety_state: dict[str, Any]) -> str:
        if bool(safety_state.get("kill_switch_active", False)):
            return "kill_switch_active"
        if bool(safety_state.get("close_only_active", False)):
            return "close_only_active"
        if bool(safety_state.get("config_close_only_active", False)):
            return "config_close_only_active"
        active_locks = list(safety_state.get("active_locks") or [])
        if active_locks:
            return str(active_locks[0].get("reason_code") or "active_lock_present")
        return ""

    @classmethod
    def _active_manual_override(cls, safety_state: dict[str, Any]) -> tuple[bool, str]:
        reason = cls._manual_override_reason(safety_state)
        return bool(reason), reason

    @staticmethod
    def _available_source_count(
        *,
        strategy_metrics: dict[str, Any],
        safety_state: dict[str, Any],
        execution_friction_measurement: dict[str, Any],
        forward_stress_regime_validation: dict[str, Any],
        recent_reconciliation_summary: dict[str, Any],
        execution_degradation_advisory: dict[str, Any],
        family_execution_degradation_advisory: dict[str, Any],
    ) -> int:
        return sum(
            1
            for payload in (
                strategy_metrics,
                safety_state,
                execution_friction_measurement,
                forward_stress_regime_validation,
                recent_reconciliation_summary,
                execution_degradation_advisory,
                family_execution_degradation_advisory,
            )
            if bool(payload)
        )

    @staticmethod
    def _trigger_axis(
        *,
        active_manual_override: bool,
        reconciliation_state: str,
        risk_gate_state: str,
        friction_state: str,
        generalization_state: str,
        kill_condition_state: str,
    ) -> str:
        if active_manual_override:
            return "manual_override_axis"
        if reconciliation_state == "critical":
            return "reconciliation_axis"
        if risk_gate_state == "closed":
            return "risk_gate_axis"
        if friction_state == "degraded":
            return "friction_axis"
        if generalization_state == "insufficient":
            return "generalization_axis"
        if kill_condition_state != "observe_only":
            return "composite_axis"
        return ""

    @staticmethod
    def _kill_condition_state(
        *,
        active_manual_override: bool,
        available_source_count: int,
        risk_gate_state: str,
        risk_gate_reason: str,
        friction_state: str,
        generalization_state: str,
        reconciliation_state: str,
        execution_degradation_state: str,
        family_execution_state: str,
    ) -> str:
        if active_manual_override:
            return "observe_only"

        if available_source_count < 2:
            return "observe_only"

        if (
            (reconciliation_state == "critical" and risk_gate_state == "closed")
            or (reconciliation_state == "critical" and friction_state == "degraded")
            or (generalization_state == "insufficient" and friction_state == "degraded")
            or (generalization_state == "insufficient" and risk_gate_state == "closed")
            or (
                risk_gate_reason in {"api_unhealthy", "infra-unhealthy", "infra_unhealthy"}
                and reconciliation_state in {"degraded", "critical"}
            )
            or (
                risk_gate_reason in {"api_unhealthy", "infra-unhealthy", "infra_unhealthy"}
                and friction_state == "degraded"
            )
        ):
            return "kill_switch_review"

        if (
            reconciliation_state == "critical"
            or risk_gate_state == "closed"
            or friction_state == "degraded"
            or generalization_state == "insufficient"
            or execution_degradation_state == "manual_review"
            or (family_execution_state == "manual_review" and friction_state in {"watch", "degraded"})
            or (family_execution_state == "manual_review" and generalization_state in {"fragile", "insufficient"})
            or (friction_state == "watch" and generalization_state == "fragile")
            or (generalization_state == "fragile" and reconciliation_state == "degraded")
        ):
            return "close_only_review"

        if (
            risk_gate_state == "throttled"
            or friction_state == "watch"
            or generalization_state == "fragile"
            or execution_degradation_state == "watch"
            or family_execution_state in {"watch", "manual_review"}
            or generalization_state == "insufficient_evidence"
        ):
            return "throttle_review"

        return "observe_only"

    @staticmethod
    def _automation_bias(kill_condition_state: str) -> str:
        return {
            "observe_only": "observe_only",
            "throttle_review": "propose_throttle",
            "close_only_review": "propose_close_only",
            "kill_switch_review": "propose_kill_switch",
        }.get(kill_condition_state, "observe_only")

    @staticmethod
    def _summary(
        *,
        kill_condition_state: str,
        active_manual_override: bool,
        manual_override_reason: str,
    ) -> str:
        if active_manual_override:
            return (
                "Current stop evidence does not justify automatic escalation because a manual safety override "
                f"is already active ({manual_override_reason})."
            )
        if kill_condition_state == "throttle_review":
            return "Current evidence justifies throttle review, but not close-only or kill-switch escalation."
        if kill_condition_state == "close_only_review":
            return "Current evidence is weak enough that close-only review should happen before new entries continue."
        if kill_condition_state == "kill_switch_review":
            return "Multiple hard-failure axes are aligned; kill-switch review is justified before trusting live operation."
        return "Current stop evidence does not justify automatic escalation beyond observation."

    @classmethod
    def generate(
        cls,
        *,
        strategy_metrics: dict[str, Any] | None,
        safety_state: dict[str, Any] | None,
        execution_friction_measurement: dict[str, Any] | None,
        forward_stress_regime_validation: dict[str, Any] | None,
        recent_reconciliation_summary: dict[str, Any] | None,
        execution_degradation_advisory: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
    ) -> dict[str, Any]:
        strategy_metrics_payload = cls._dict(strategy_metrics)
        safety_state_payload = cls._dict(safety_state)
        friction_payload = cls._dict(execution_friction_measurement)
        generalization_payload = cls._dict(forward_stress_regime_validation)
        reconciliation_payload = cls._dict(recent_reconciliation_summary)
        execution_degradation_payload = cls._dict(execution_degradation_advisory)
        family_execution_payload = cls._dict(family_execution_degradation_advisory)

        available = any(
            (
                strategy_metrics_payload,
                safety_state_payload,
                friction_payload,
                generalization_payload,
                reconciliation_payload,
                execution_degradation_payload,
                family_execution_payload,
            )
        )
        if not available:
            return {
                "available": False,
                "advisory_only": True,
                "kill_condition_state": "observe_only",
                "automation_bias": "observe_only",
                "write_scope": "none",
                "trigger_axis": "",
                "trigger_reason_codes": [],
                "reason_codes": [],
                "active_manual_override": False,
                "manual_override_reason": "",
                "arm_required": False,
                "summary": "Kill-condition automation evidence is unavailable; keep stop review informational only.",
                "source_summary": {},
            }

        risk_gate_state = cls._normalize_risk_gate_state(strategy_metrics_payload)
        risk_gate_reason = str(strategy_metrics_payload.get("risk_reason") or "unknown")
        friction_state = cls._normalize_friction_state(friction_payload)
        generalization_state = cls._normalize_generalization_state(generalization_payload)
        reconciliation_state = cls._normalize_reconciliation_state(reconciliation_payload)
        execution_degradation_state = cls._normalize_execution_degradation_state(execution_degradation_payload)
        family_execution_state = cls._normalize_family_execution_state(family_execution_payload)
        active_manual_override, manual_override_reason = cls._active_manual_override(safety_state_payload)
        available_source_count = cls._available_source_count(
            strategy_metrics=strategy_metrics_payload,
            safety_state=safety_state_payload,
            execution_friction_measurement=friction_payload,
            forward_stress_regime_validation=generalization_payload,
            recent_reconciliation_summary=reconciliation_payload,
            execution_degradation_advisory=execution_degradation_payload,
            family_execution_degradation_advisory=family_execution_payload,
        )

        kill_condition_state = cls._kill_condition_state(
            active_manual_override=active_manual_override,
            available_source_count=available_source_count,
            risk_gate_state=risk_gate_state,
            risk_gate_reason=risk_gate_reason,
            friction_state=friction_state,
            generalization_state=generalization_state,
            reconciliation_state=reconciliation_state,
            execution_degradation_state=execution_degradation_state,
            family_execution_state=family_execution_state,
        )
        automation_bias = cls._automation_bias(kill_condition_state)
        trigger_axis = cls._trigger_axis(
            active_manual_override=active_manual_override,
            reconciliation_state=reconciliation_state,
            risk_gate_state=risk_gate_state,
            friction_state=friction_state,
            generalization_state=generalization_state,
            kill_condition_state=kill_condition_state,
        )
        write_scope = "none" if active_manual_override else "proposal_only"
        arm_required = bool(kill_condition_state != "observe_only" and not active_manual_override)

        reason_codes = cls._dedupe(
            [
                f"kill_condition:{kill_condition_state}",
                f"risk_gate:{risk_gate_state}",
                f"friction:{friction_state}",
                f"generalization:{generalization_state}",
                f"reconciliation:{reconciliation_state}",
                f"execution_degradation:{execution_degradation_state}",
                f"family_execution_degradation:{family_execution_state}",
                f"risk_gate_reason:{risk_gate_reason}",
                (
                    f"manual_override:{manual_override_reason}"
                    if active_manual_override and manual_override_reason
                    else ""
                ),
                (
                    f"friction_axis:{friction_payload.get('weakest_axis')}"
                    if friction_payload.get("weakest_axis")
                    else ""
                ),
                (
                    f"generalization_axis:{generalization_payload.get('weakest_axis')}"
                    if generalization_payload.get("weakest_axis")
                    else ""
                ),
            ]
        )

        source_summary = {
            "risk_gate_state": risk_gate_state,
            "risk_gate_reason": risk_gate_reason,
            "friction_state": friction_state,
            "friction_weakest_axis": str(friction_payload.get("weakest_axis") or ""),
            "generalization_state": generalization_state,
            "generalization_weakest_axis": str(generalization_payload.get("weakest_axis") or ""),
            "reconciliation_state": reconciliation_state,
            "execution_degradation_state": execution_degradation_state,
            "family_execution_degradation_state": family_execution_state,
            "kill_switch_active": bool(safety_state_payload.get("kill_switch_active", False)),
            "close_only_active": bool(safety_state_payload.get("close_only_active", False)),
            "config_close_only_active": bool(safety_state_payload.get("config_close_only_active", False)),
            "active_lock_count": len(list(safety_state_payload.get("active_locks") or [])),
            "matching_lock_count": len(list(safety_state_payload.get("matching_locks") or [])),
            "available_source_count": available_source_count,
            "write_targets": [
                "safety_locks.set_close_only",
                "safety_locks.set_kill_switch",
            ],
        }

        return {
            "available": True,
            "advisory_only": True,
            "kill_condition_state": kill_condition_state,
            "automation_bias": automation_bias,
            "write_scope": write_scope,
            "trigger_axis": trigger_axis,
            "trigger_reason_codes": list(reason_codes),
            "reason_codes": list(reason_codes),
            "active_manual_override": active_manual_override,
            "manual_override_reason": manual_override_reason,
            "arm_required": arm_required,
            "summary": cls._summary(
                kill_condition_state=kill_condition_state,
                active_manual_override=active_manual_override,
                manual_override_reason=manual_override_reason,
            ),
            "source_summary": source_summary,
        }
