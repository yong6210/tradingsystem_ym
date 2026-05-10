from __future__ import annotations

from typing import Any


class ForwardStressRegimeValidationService:
    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

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
    def _coverage_state(
        cls,
        *,
        wf_trades: int,
        eligible_closed_trades: int,
        execution_data_trades: int,
    ) -> str:
        if wf_trades < 8 or eligible_closed_trades < 8:
            return "thin_validation"
        if wf_trades < 20 or eligible_closed_trades < 20 or execution_data_trades < 8:
            return "usable_validation"
        return "mature_validation"

    @classmethod
    def _walk_forward_state(cls, *, wf_trades: int, mean_ev: float, p5_ev: float) -> str:
        if wf_trades == 0:
            return "insufficient_walk_forward"
        if wf_trades >= 8 and mean_ev > 0.0 and p5_ev > -0.8:
            return "validated_walk_forward"
        return "fragile_walk_forward"

    @classmethod
    def _stress_state(cls, *, strategy_v2_stress_validation: dict[str, Any]) -> tuple[str, str]:
        payload = dict(strategy_v2_stress_validation or {})
        sample_counts = dict(payload.get("sample_counts") or {})
        recommendation = dict(payload.get("deployment_recommendation") or {})
        eligible_closed_trades = cls._int(sample_counts.get("eligible_closed_trades", 0))
        reason = str(recommendation.get("reason") or "not_available")
        if not payload or not cls._safe_bool(payload.get("available", False)) or eligible_closed_trades == 0:
            return "insufficient_stress", reason
        if (
            not cls._safe_bool(recommendation.get("stress_pass", False))
            or reason.startswith("scenario_catastrophic_drawdown")
            or reason.startswith("replay_divergence_fail")
            or reason.startswith("replay_divergence_warn")
            or reason.startswith("scenario_degraded")
        ):
            return "fragile_stress", reason
        return "validated_stress", reason

    @classmethod
    def _replay_state(
        cls,
        *,
        strategy_v2_stress_replay_assessment: dict[str, Any],
        strategy_v2_stress_replay_lineage: dict[str, Any],
    ) -> tuple[str, str]:
        assessment = dict(strategy_v2_stress_replay_assessment or {})
        lineage = dict(strategy_v2_stress_replay_lineage or {})
        assessment_reason = str(assessment.get("reason") or "not_available")
        recommendation = dict(assessment.get("deployment_recommendation") or {})
        decision = str(recommendation.get("decision") or "keep_approximation")
        if (
            not lineage
            or not cls._safe_bool(lineage.get("available", False))
            or not cls._safe_bool(lineage.get("runtime_inputs_ready", False))
            or assessment_reason == "insufficient_runtime_lineage"
        ):
            return "replay_lineage_thin", assessment_reason
        if (
            decision in {"prepare_full_replay", "promote_true_market_runner"}
            or cls._safe_bool(assessment.get("replacement_recommended", False))
            or cls._safe_bool(recommendation.get("true_runner_promotion_ready", False))
        ):
            return "replay_followup_required", decision
        return "approximation_confirmed", decision

    @classmethod
    def _split_state(cls, *, metrics: dict[str, Any], prefix: str) -> tuple[str, str]:
        rows = {
            str(name or "").strip().lower(): dict(payload or {})
            for name, payload in dict(metrics or {}).items()
        }
        meaningful = {
            name: row
            for name, row in rows.items()
            if cls._int(row.get("trades", 0)) >= 3
        }
        if len(meaningful) < 2:
            return f"insufficient_{prefix}_split", ""

        fragile_bucket = ""
        for name, row in meaningful.items():
            if (
                cls._float(row.get("ev", 0.0)) <= 0.0
                or cls._float(row.get("p5_ev", 0.0)) <= -0.8
                or cls._float(row.get("time_failure_ratio", 0.0)) >= 0.35
            ):
                fragile_bucket = name
                break
        if fragile_bucket:
            return f"fragile_{prefix}_split", fragile_bucket
        return f"validated_{prefix}_split", ""

    @classmethod
    def _validation_state(
        cls,
        *,
        coverage_state: str,
        walk_forward_state: str,
        walk_forward_mean_ev: float,
        stress_state: str,
        stress_reason: str,
        replay_state: str,
        regime_split_state: str,
        session_split_state: str,
    ) -> str:
        if (
            coverage_state == "thin_validation"
            or walk_forward_state == "insufficient_walk_forward"
            or stress_state == "insufficient_stress"
            or (
                regime_split_state == "insufficient_regime_split"
                and session_split_state == "insufficient_session_split"
            )
        ):
            return "insufficient_evidence"

        if (
            (walk_forward_state == "fragile_walk_forward" and walk_forward_mean_ev <= 0.0)
            or stress_reason.startswith("scenario_catastrophic_drawdown")
            or stress_reason.startswith("replay_divergence_fail")
            or (replay_state == "replay_lineage_thin" and stress_state == "fragile_stress")
            or (
                regime_split_state == "fragile_regime_split"
                and session_split_state == "fragile_session_split"
            )
        ):
            return "insufficient_generalization"

        if (
            coverage_state == "usable_validation"
            or walk_forward_state == "fragile_walk_forward"
            or stress_state == "fragile_stress"
            or replay_state == "replay_followup_required"
            or regime_split_state == "fragile_regime_split"
            or session_split_state == "fragile_session_split"
        ):
            return "fragile_generalization"

        return "validated_generalization"

    @staticmethod
    def _validation_bias(validation_state: str) -> str:
        return {
            "validated_generalization": "support_current_validation",
            "fragile_generalization": "monitor_regime_stress_fragility",
            "insufficient_generalization": "reduce_deployment_confidence",
            "insufficient_evidence": "gather_more_validation_evidence",
        }.get(validation_state, "gather_more_validation_evidence")

    @staticmethod
    def _weakest_axis(
        *,
        coverage_state: str,
        walk_forward_state: str,
        stress_state: str,
        replay_state: str,
        regime_split_state: str,
        session_split_state: str,
    ) -> str:
        priority = (
            ("stress_state", stress_state, {"fragile_stress", "insufficient_stress"}),
            ("walk_forward_state", walk_forward_state, {"fragile_walk_forward", "insufficient_walk_forward"}),
            ("replay_state", replay_state, {"replay_followup_required", "replay_lineage_thin"}),
            ("regime_split_state", regime_split_state, {"fragile_regime_split", "insufficient_regime_split"}),
            ("session_split_state", session_split_state, {"fragile_session_split", "insufficient_session_split"}),
            ("coverage_state", coverage_state, {"usable_validation", "thin_validation"}),
        )
        for axis, value, negatives in priority:
            if value in negatives:
                return axis
        return ""

    @classmethod
    def _summary(
        cls,
        *,
        validation_state: str,
        weakest_axis: str,
        preferred_live_mode: str,
        worst_scenario: str,
        best_regime: str,
        best_session: str,
    ) -> str:
        if validation_state == "validated_generalization":
            return (
                "Current forward proxy, stress, and regime/session split evidence still supports the existing "
                f"validation posture. preferred_live_mode={preferred_live_mode}, best_regime={best_regime or 'none'}, "
                f"best_session={best_session or 'none'}."
            )
        if validation_state == "fragile_generalization":
            if weakest_axis == "stress_state":
                return (
                    f"Generalization still holds directionally, but stress evidence is fragile around "
                    f"{worst_scenario or 'stressed_cost'}; monitor deployment confidence before trusting current validation."
                )
            if weakest_axis == "replay_state":
                return (
                    "Generalization still looks directionally usable, but replay lineage or replay follow-up pressure "
                    "means approximation confidence is not fully settled."
                )
            if weakest_axis == "regime_split_state":
                return (
                    f"Generalization still has some support, but regime split fragility remains visible; "
                    f"best_regime={best_regime or 'none'} should not be treated as universally stable."
                )
            if weakest_axis == "session_split_state":
                return (
                    f"Generalization still has some support, but session split fragility remains visible; "
                    f"best_session={best_session or 'none'} should not be treated as universally stable."
                )
            return (
                "Generalization still holds directionally, but current forward/stress evidence is fragile enough "
                "that deployment confidence should stay under monitoring."
            )
        if validation_state == "insufficient_generalization":
            return (
                "Current forward or stress evidence is weak enough that deployment confidence should be treated as "
                "reduced until validation quality improves."
            )
        return "Validation evidence is still too thin to treat current generalization as stable."

    @classmethod
    def generate(
        cls,
        *,
        walk_forward: dict[str, Any] | None,
        strategy_v2_validation: dict[str, Any] | None,
        strategy_v2_stress_validation: dict[str, Any] | None,
        strategy_v2_stress_replay_assessment: dict[str, Any] | None,
        strategy_v2_stress_replay_lineage: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        wf = cls._dict(walk_forward)
        v2 = cls._dict(strategy_v2_validation)
        stress = cls._dict(strategy_v2_stress_validation)
        replay_assessment = cls._dict(strategy_v2_stress_replay_assessment)
        replay_lineage = cls._dict(strategy_v2_stress_replay_lineage)

        if not any([wf, v2, stress, replay_assessment, replay_lineage]):
            return None

        wf_trades = cls._int(wf.get("trades", 0))
        wf_mean_ev = cls._float(wf.get("mean_ev", 0.0))
        wf_p5_ev = cls._float(wf.get("p5_ev", 0.0))
        v2_sample_counts = dict(v2.get("sample_counts") or {})
        eligible_closed_trades = cls._int(v2_sample_counts.get("eligible_closed_trades", 0))
        preferred_live_mode = str(
            dict(v2.get("deployment_recommendation") or {}).get("preferred_live_mode") or "A_ONLY"
        ).upper()
        best_regime = str(dict(dict(v2.get("regime_summary") or {}).get("best_ev_regime") or {}).get("name") or "")
        best_session = str(
            dict(dict(v2.get("session_summary") or {}).get("best_ev_session") or {}).get("name") or ""
        )

        stress_sample_counts = dict(stress.get("sample_counts") or {})
        execution_data_trades = cls._int(stress_sample_counts.get("execution_data_trades", 0))
        stress_recommendation = dict(stress.get("deployment_recommendation") or {})
        worst_scenario = str(
            stress_recommendation.get("worst_scenario")
            or dict(replay_assessment.get("scenario_evidence") or {}).get("worst_scenario")
            or "stressed_cost"
        )

        coverage_state = cls._coverage_state(
            wf_trades=wf_trades,
            eligible_closed_trades=eligible_closed_trades,
            execution_data_trades=execution_data_trades,
        )
        walk_forward_state = cls._walk_forward_state(
            wf_trades=wf_trades,
            mean_ev=wf_mean_ev,
            p5_ev=wf_p5_ev,
        )
        stress_state, stress_reason = cls._stress_state(strategy_v2_stress_validation=stress)
        replay_state, replay_reason = cls._replay_state(
            strategy_v2_stress_replay_assessment=replay_assessment,
            strategy_v2_stress_replay_lineage=replay_lineage,
        )
        regime_split_state, fragile_regime_bucket = cls._split_state(
            metrics=dict(v2.get("regime_metrics") or {}),
            prefix="regime",
        )
        session_split_state, fragile_session_bucket = cls._split_state(
            metrics=dict(v2.get("session_metrics") or {}),
            prefix="session",
        )
        validation_state = cls._validation_state(
            coverage_state=coverage_state,
            walk_forward_state=walk_forward_state,
            walk_forward_mean_ev=wf_mean_ev,
            stress_state=stress_state,
            stress_reason=stress_reason,
            replay_state=replay_state,
            regime_split_state=regime_split_state,
            session_split_state=session_split_state,
        )
        validation_bias = cls._validation_bias(validation_state)
        weakest_axis = cls._weakest_axis(
            coverage_state=coverage_state,
            walk_forward_state=walk_forward_state,
            stress_state=stress_state,
            replay_state=replay_state,
            regime_split_state=regime_split_state,
            session_split_state=session_split_state,
        )

        reason_codes: list[str] = []
        if coverage_state == "thin_validation":
            reason_codes.append("thin_validation_coverage")
        elif coverage_state == "usable_validation":
            reason_codes.append("usable_validation_coverage")
        if wf_mean_ev <= 0.0:
            reason_codes.append("walk_forward_mean_ev_non_positive")
        if wf_p5_ev <= -0.8:
            reason_codes.append("walk_forward_p5_below_threshold")
        if stress_reason.startswith("scenario_catastrophic_drawdown"):
            reason_codes.append("stress_catastrophic_drawdown")
        elif stress_reason.startswith("replay_divergence_fail"):
            reason_codes.append("stress_replay_divergence_fail")
        elif stress_reason.startswith("replay_divergence_warn"):
            reason_codes.append("stress_replay_divergence_warn")
        elif stress_reason.startswith("scenario_degraded"):
            reason_codes.append("stress_scenario_degraded")
        if replay_state == "replay_lineage_thin":
            reason_codes.append("replay_lineage_thin")
        elif replay_state == "replay_followup_required":
            reason_codes.append("replay_followup_required")
        if regime_split_state == "fragile_regime_split":
            reason_codes.append("fragile_regime_bucket")
        elif regime_split_state == "insufficient_regime_split":
            reason_codes.append("insufficient_regime_split")
        if session_split_state == "fragile_session_split":
            reason_codes.append("fragile_session_bucket")
        elif session_split_state == "insufficient_session_split":
            reason_codes.append("insufficient_session_split")

        return {
            "available": bool(wf or v2 or stress or replay_assessment or replay_lineage),
            "advisory_only": True,
            "validation_state": validation_state,
            "validation_bias": validation_bias,
            "coverage_state": coverage_state,
            "walk_forward_state": walk_forward_state,
            "stress_state": stress_state,
            "replay_state": replay_state,
            "regime_split_state": regime_split_state,
            "session_split_state": session_split_state,
            "preferred_live_mode": preferred_live_mode,
            "worst_scenario": worst_scenario,
            "best_regime": best_regime,
            "best_session": best_session,
            "weakest_axis": weakest_axis,
            "summary": cls._summary(
                validation_state=validation_state,
                weakest_axis=weakest_axis,
                preferred_live_mode=preferred_live_mode,
                worst_scenario=worst_scenario,
                best_regime=best_regime,
                best_session=best_session,
            ),
            "reason_codes": cls._dedupe(reason_codes),
            "source_summary": {
                "walk_forward": {
                    "trades": wf_trades,
                    "mean_ev": round(wf_mean_ev, 4),
                    "p5_ev": round(wf_p5_ev, 4),
                },
                "strategy_v2_validation": {
                    "available": cls._safe_bool(v2.get("available", False)),
                    "eligible_closed_trades": eligible_closed_trades,
                    "preferred_live_mode": preferred_live_mode,
                    "best_regime": best_regime,
                    "best_session": best_session,
                    "fragile_regime_bucket": fragile_regime_bucket,
                    "fragile_session_bucket": fragile_session_bucket,
                },
                "strategy_v2_stress_validation": {
                    "available": cls._safe_bool(stress.get("available", False)),
                    "stress_pass": cls._safe_bool(stress_recommendation.get("stress_pass", False)),
                    "reason": stress_reason,
                    "worst_scenario": worst_scenario,
                    "replay_gate_applied": cls._safe_bool(stress_recommendation.get("replay_gate_applied", False)),
                    "divergence_gate_applied": cls._safe_bool(stress_recommendation.get("divergence_gate_applied", False)),
                    "execution_data_trades": execution_data_trades,
                },
                "strategy_v2_stress_replay_assessment": {
                    "available": cls._safe_bool(replay_assessment.get("available", False)),
                    "decision": str(
                        dict(replay_assessment.get("deployment_recommendation") or {}).get("decision")
                        or "keep_approximation"
                    ),
                    "reason": str(replay_assessment.get("reason") or "not_available"),
                    "replacement_recommended": cls._safe_bool(replay_assessment.get("replacement_recommended", False)),
                    "true_runner_promotion_ready": cls._safe_bool(
                        dict(replay_assessment.get("deployment_recommendation") or {}).get(
                            "true_runner_promotion_ready", False
                        )
                    ),
                },
                "strategy_v2_stress_replay_lineage": {
                    "available": cls._safe_bool(replay_lineage.get("available", False)),
                    "runtime_inputs_ready": cls._safe_bool(replay_lineage.get("runtime_inputs_ready", False)),
                    "reason": replay_reason,
                    "coverage": dict(replay_lineage.get("coverage") or {}),
                },
            },
        }
