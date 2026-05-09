from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, ClassVar

from app.core.config import Settings, get_settings


class StrategyV2StressReplayAssessmentService:
    _MIN_SAMPLE_SIZE = 30
    _REPLACEMENT_DECISIONS: ClassVar[set[str]] = {"prepare_full_replay", "recommend_full_replay"}

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(float(numerator) / float(denominator), 4)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if isfinite(parsed) else default

    @classmethod
    def _safe_int(cls, value: Any, default: int = 0) -> int:
        return int(cls._safe_float(value, float(default)))

    @classmethod
    def _candle_latency_hits(cls, latency_source_counts: dict[str, int]) -> int:
        return sum(
            cls._safe_int(count)
            for source, count in (latency_source_counts or {}).items()
            if str(source).startswith("candle_open:")
        )

    @classmethod
    def _fallback_latency_hits(cls, latency_source_counts: dict[str, int]) -> int:
        return sum(
            cls._safe_int(count)
            for source, count in (latency_source_counts or {}).items()
            if str(source).startswith("fallback_slippage:")
        )

    @staticmethod
    def _scenario_statuses(stress_validation: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return dict((dict(stress_validation.get("deployment_recommendation") or {})).get("scenario_statuses") or {})

    def _decision(
        self,
        *,
        eligible_closed_trades: int,
        execution_fill_coverage: float,
        latency_candle_coverage: float,
        min_execution_fill_coverage: float,
        min_latency_candle_coverage: float,
        degraded_scenarios: list[str],
        catastrophic_scenarios: list[str],
    ) -> tuple[bool, bool, str, str, list[str], list[str]]:
        blockers: list[str] = []
        next_steps: list[str] = []
        full_replay_ready = False
        replacement_recommended = False

        if eligible_closed_trades < self._MIN_SAMPLE_SIZE:
            blockers.append("insufficient_closed_trade_samples_for_replay_upgrade")
            next_steps.append("accumulate more closed v2 trades before deciding on full replay replacement")
            return False, False, "keep_approximation", "insufficient_stress_samples", blockers, next_steps

        if execution_fill_coverage < float(min_execution_fill_coverage):
            blockers.append("execution_fill_coverage_below_threshold")
        if latency_candle_coverage < float(min_latency_candle_coverage):
            blockers.append("latency_candle_coverage_below_threshold")

        if blockers:
            next_steps.extend(
                [
                    "increase execution fill coverage for closed v2 trades",
                    "improve 5m latency reference coverage for stress replay candidates",
                ]
            )
            return False, False, "keep_approximation", "insufficient_runtime_lineage", blockers, next_steps

        full_replay_ready = True
        if catastrophic_scenarios:
            replacement_recommended = True
            next_steps.extend(
                [
                    "design counterfactual fill replay over saved candle/fill timeline",
                    "replace heuristic shock/latency penalty with replay-derived path simulation",
                ]
            )
            return (
                full_replay_ready,
                replacement_recommended,
                "recommend_full_replay",
                f"catastrophic_stress_detected:{catastrophic_scenarios[0]}",
                blockers,
                next_steps,
            )

        if len(degraded_scenarios) >= 2:
            replacement_recommended = True
            next_steps.extend(
                [
                    "prototype full replay on worst degraded stress scenarios first",
                    "compare replay-derived stress outputs against current approximation payload",
                ]
            )
            return (
                full_replay_ready,
                replacement_recommended,
                "prepare_full_replay",
                f"multiple_degraded_scenarios:{','.join(degraded_scenarios)}",
                blockers,
                next_steps,
            )

        next_steps.extend(
            [
                "keep current approximation for deployment decisions",
                "revisit full replay only after more degraded stress samples accumulate",
            ]
        )
        return full_replay_ready, replacement_recommended, "keep_approximation", "approximation_sufficient_for_now", blockers, next_steps

    def _true_runner_readiness(
        self,
        *,
        full_replay_ready: bool,
        replacement_recommended: bool,
        execution_fill_coverage: float,
        latency_candle_coverage: float,
        candle_path_coverage: float,
        degraded_scenarios: list[str],
        catastrophic_scenarios: list[str],
        worst_scenario: str,
        stress_replay_output_artifacts: dict[str, Any],
    ) -> dict[str, Any]:
        critical_scenarios = list(dict.fromkeys([*catastrophic_scenarios, *degraded_scenarios]))
        if not critical_scenarios and worst_scenario not in {"", "stressed_cost"}:
            critical_scenarios = [worst_scenario]

        min_exec = self._safe_float(self.settings.stress_true_replay_min_execution_fill_coverage, 0.85)
        min_latency = self._safe_float(self.settings.stress_true_replay_min_latency_candle_coverage, 0.80)
        min_path = self._safe_float(self.settings.stress_true_replay_min_candle_path_coverage, 0.90)
        min_compared = self._safe_int(self.settings.stress_true_replay_min_scenarios_compared, 2)

        summary_counts = dict(stress_replay_output_artifacts.get("summary_counts") or {})
        scenario_outputs = dict(stress_replay_output_artifacts.get("scenario_outputs") or {})
        scenarios_compared = self._safe_int(summary_counts.get("scenarios_compared", 0))
        available_outputs = [
            name
            for name, row in scenario_outputs.items()
            if bool((dict(row or {})).get("available", False)) and bool((dict(row or {})).get("summary"))
        ]
        critical_scenarios_with_outputs = [name for name in critical_scenarios if name in available_outputs]

        blocked_by: list[str] = []
        next_steps: list[str] = []
        if not full_replay_ready:
            blocked_by.append("true_runner_base_readiness_not_met")
        if not replacement_recommended:
            blocked_by.append("true_runner_upgrade_not_recommended")
        if execution_fill_coverage < min_exec:
            blocked_by.append("true_runner_execution_fill_coverage_below_threshold")
        if latency_candle_coverage < min_latency:
            blocked_by.append("true_runner_latency_candle_coverage_below_threshold")
        if candle_path_coverage < min_path:
            blocked_by.append("true_runner_candle_path_coverage_below_threshold")
        if not bool(stress_replay_output_artifacts.get("available", False)):
            blocked_by.append("prototype_replay_outputs_unavailable")
        if not bool(stress_replay_output_artifacts.get("comparison_ready", False)):
            blocked_by.append("prototype_replay_outputs_not_compared")
        if scenarios_compared < min_compared:
            blocked_by.append("prototype_replay_output_coverage_below_threshold")
        if critical_scenarios and len(critical_scenarios_with_outputs) < len(critical_scenarios):
            blocked_by.append("critical_replay_scenarios_missing_output")

        if "true_runner_base_readiness_not_met" in blocked_by:
            next_steps.append("keep prototype replay worker until base replay readiness is met")
        if "true_runner_upgrade_not_recommended" in blocked_by:
            next_steps.append("keep approximation/prototype path until stress evidence justifies true runner replacement")
        if any(
            item in blocked_by
            for item in (
                "true_runner_execution_fill_coverage_below_threshold",
                "true_runner_latency_candle_coverage_below_threshold",
                "true_runner_candle_path_coverage_below_threshold",
            )
        ):
            next_steps.append("raise lineage quality to true-runner thresholds before replacing the prototype worker")
        if any(
            item in blocked_by
            for item in (
                "prototype_replay_outputs_unavailable",
                "prototype_replay_outputs_not_compared",
                "prototype_replay_output_coverage_below_threshold",
                "critical_replay_scenarios_missing_output",
            )
        ):
            next_steps.append("materialize prototype replay outputs for all critical degraded/catastrophic scenarios first")

        true_runner_ready = not blocked_by
        stage = "ready_for_true_market_runner" if true_runner_ready else "prototype_only"
        return {
            "true_runner_ready": true_runner_ready,
            "stage": stage,
            "critical_scenarios": critical_scenarios,
            "critical_scenarios_with_outputs": critical_scenarios_with_outputs,
            "prototype_output_available_scenarios": available_outputs,
            "scenarios_compared": scenarios_compared,
            "gates": {
                "min_execution_fill_coverage": min_exec,
                "min_latency_candle_coverage": min_latency,
                "min_candle_path_coverage": min_path,
                "min_scenarios_compared": min_compared,
                "execution_fill_coverage": round(execution_fill_coverage, 4),
                "latency_candle_coverage": round(latency_candle_coverage, 4),
                "candle_path_coverage": round(candle_path_coverage, 4),
            },
            "blocked_by": blocked_by,
            "next_steps": list(dict.fromkeys(next_steps)),
        }

    @classmethod
    def _replay_output_lineage_alignment(
        cls,
        *,
        stress_replay_output_artifacts: dict[str, Any] | None,
        pbo_dsr_metrics: dict[str, Any] | None,
    ) -> dict[str, Any]:
        artifacts_payload = dict(stress_replay_output_artifacts or {})
        metrics_payload = dict(pbo_dsr_metrics or {})
        lineage_audit = dict(metrics_payload.get("lineage_audit") or {})
        summary_counts = dict(artifacts_payload.get("summary_counts") or {})
        lineage_summary = dict(artifacts_payload.get("lineage_summary") or {})
        scenarios_compared = cls._safe_int(summary_counts.get("scenarios_compared", 0))
        available = bool(artifacts_payload.get("available", False)) and scenarios_compared > 0
        selected_trial_writer_source = str(lineage_audit.get("selected_trial_writer_source", "unknown"))
        selected_trial_selection_rule = str(lineage_audit.get("selected_trial_selection_rule", ""))
        selected_trial_from_runtime_proxy = bool(lineage_audit.get("selected_trial_from_runtime_proxy", False))
        selected_trial_from_true_threshold = bool(lineage_audit.get("selected_trial_from_true_threshold", False))
        threshold_lineage_audit_status = str(lineage_audit.get("audit_status", "not_available"))
        if not available:
            status = "NOT_AVAILABLE"
            reason = "replay_output_lineage_unavailable"
            gate_applied = False
        elif selected_trial_from_true_threshold:
            status = "PASS"
            reason = "replay_output_lineage_available_and_selected_trial_from_true_threshold"
            gate_applied = True
        elif selected_trial_from_runtime_proxy:
            status = "WARN"
            reason = "selected_trial_from_runtime_proxy_with_replay_output_lineage"
            gate_applied = True
        elif threshold_lineage_audit_status == "PASS":
            status = "PASS"
            reason = "replay_output_lineage_available_and_threshold_lineage_audit_pass"
            gate_applied = True
        else:
            status = "WARN"
            reason = "replay_output_lineage_available_selected_trial_source_unresolved"
            gate_applied = True
        return {
            "available": available,
            "gate_applied": gate_applied,
            "status": status,
            "reason": reason,
            "scenarios_compared": scenarios_compared,
            "compared_scenarios": list(lineage_summary.get("compared_scenarios") or []),
            "scenarios_with_lineage": list(lineage_summary.get("scenarios_with_lineage") or []),
            "worker_modes": list(lineage_summary.get("worker_modes") or []),
            "input_batch_count": cls._safe_int(lineage_summary.get("input_batch_count", 0)),
            "input_trade_rows": cls._safe_int(lineage_summary.get("input_trade_rows", 0)),
            "selected_trial_writer_source": selected_trial_writer_source,
            "selected_trial_selection_rule": selected_trial_selection_rule,
            "selected_trial_from_runtime_proxy": selected_trial_from_runtime_proxy,
            "selected_trial_from_true_threshold": selected_trial_from_true_threshold,
        }

    @classmethod
    def _approval_cross_display(
        cls,
        *,
        stress_validation: dict[str, Any] | None,
        stress_replay_output_artifacts: dict[str, Any] | None,
        pbo_dsr_metrics: dict[str, Any] | None,
    ) -> dict[str, Any]:
        stress_payload = dict(stress_validation or {})
        stress_recommendation = dict(stress_payload.get("deployment_recommendation") or {})
        scenario_statuses = dict(stress_recommendation.get("scenario_statuses") or {})
        artifacts_payload = dict(stress_replay_output_artifacts or {})
        scenario_outputs = dict(artifacts_payload.get("scenario_outputs") or {})
        lineage_summary = dict(artifacts_payload.get("lineage_summary") or {})
        metrics_payload = dict(pbo_dsr_metrics or {})
        selected_trial = dict(metrics_payload.get("selected_trial") or {})
        lineage_audit = dict(metrics_payload.get("lineage_audit") or {})

        threshold_lineage_winner_source = str(
            selected_trial.get("writer_source") or lineage_audit.get("selected_trial_writer_source", "unknown")
        )
        threshold_lineage_winner_selection_rule = str(
            selected_trial.get("selection_rule") or lineage_audit.get("selected_trial_selection_rule", "")
        )
        threshold_lineage_winner_run_id = str(selected_trial.get("trial_run_id") or "")
        threshold_lineage_from_runtime_proxy = bool(lineage_audit.get("selected_trial_from_runtime_proxy", False))
        threshold_lineage_from_true_threshold = bool(lineage_audit.get("selected_trial_from_true_threshold", False))
        if threshold_lineage_from_true_threshold:
            threshold_lineage_winner_type = "true_threshold"
        elif threshold_lineage_from_runtime_proxy:
            threshold_lineage_winner_type = "runtime_proxy"
        else:
            threshold_lineage_winner_type = "unresolved"

        worst_scenario = str(stress_recommendation.get("worst_scenario", "stressed_cost"))
        worst_scenario_source = str(stress_recommendation.get("worst_scenario_source", "stressed_cost"))
        worst_scenario_row = dict(scenario_statuses.get(worst_scenario) or {})
        worst_scenario_status = str(worst_scenario_row.get("status", "NOT_AVAILABLE"))
        worst_scenario_reason = str(worst_scenario_row.get("reason", stress_recommendation.get("reason", "not_available")))
        worst_scenario_divergence_status = str(worst_scenario_row.get("divergence_status", "NOT_AVAILABLE"))
        worst_scenario_divergence_reason = str(
            worst_scenario_row.get("divergence_reason", "not_available")
            if "divergence_reason" in worst_scenario_row
            else "not_available"
        )
        worst_scenario_has_output_lineage = bool((dict(scenario_outputs.get(worst_scenario) or {})).get("available", False))
        if worst_scenario_source == "stressed_cost" and worst_scenario_has_output_lineage:
            worst_scenario_source = "replay_output"
        replay_output_compared_scenarios = list(lineage_summary.get("compared_scenarios") or [])

        available = bool(metrics_payload) and bool(stress_payload)
        if not available:
            cross_display_status = "NOT_AVAILABLE"
            cross_display_reason = "approval_cross_display_inputs_unavailable"
        elif threshold_lineage_winner_type == "unresolved":
            cross_display_status = "REVIEW"
            cross_display_reason = "threshold_lineage_winner_unresolved"
        elif worst_scenario_source != "replay_output":
            cross_display_status = "REVIEW"
            cross_display_reason = "worst_scenario_not_replay_derived"
        elif threshold_lineage_winner_type == "runtime_proxy":
            cross_display_status = "REVIEW"
            cross_display_reason = "runtime_proxy_winner_with_replay_worst_scenario"
        elif worst_scenario_status == "FAIL":
            cross_display_status = "REVIEW"
            cross_display_reason = "true_threshold_winner_with_replay_fail_worst_scenario"
        elif worst_scenario_status == "WARN":
            cross_display_status = "REVIEW"
            cross_display_reason = "true_threshold_winner_with_replay_warn_worst_scenario"
        else:
            cross_display_status = "PASS"
            cross_display_reason = "true_threshold_winner_cross_displayed_with_replay_worst_scenario"

        approval_warning_locked = False
        approval_warning_code = "none"
        approval_warning_message = "approval_template_cross_display_is_consistent"
        if threshold_lineage_winner_type == "runtime_proxy" and worst_scenario_source == "replay_output":
            approval_warning_locked = True
            approval_warning_code = "proxy_selected_trial_against_replay_backed_worst_scenario"
            approval_warning_message = (
                "runtime proxy selected-trial remains active while replay-backed worst scenario is driving downside; "
                "do not treat this approval template as threshold-lineage confirmed"
            )
        elif threshold_lineage_winner_type == "unresolved":
            approval_warning_locked = True
            approval_warning_code = "threshold_lineage_winner_unresolved"
            approval_warning_message = (
                "selected-trial lineage winner is unresolved; approval review must stay manual until threshold lineage is identified"
            )
        elif worst_scenario_source != "replay_output":
            approval_warning_locked = True
            approval_warning_code = "replay_backed_worst_scenario_missing"
            approval_warning_message = (
                "worst stress scenario is not replay-backed yet; approval template is still relying on approximation-side downside evidence"
            )

        return {
            "available": available,
            "cross_display_status": cross_display_status,
            "cross_display_reason": cross_display_reason,
            "threshold_lineage_winner_run_id": threshold_lineage_winner_run_id or None,
            "threshold_lineage_winner_source": threshold_lineage_winner_source,
            "threshold_lineage_winner_selection_rule": threshold_lineage_winner_selection_rule,
            "threshold_lineage_winner_type": threshold_lineage_winner_type,
            "threshold_lineage_audit_status": str(lineage_audit.get("audit_status", "not_available")),
            "replay_derived_worst_scenario": worst_scenario,
            "replay_derived_worst_scenario_source": worst_scenario_source,
            "replay_derived_worst_scenario_status": worst_scenario_status,
            "replay_derived_worst_scenario_reason": worst_scenario_reason,
            "replay_derived_worst_scenario_divergence_status": worst_scenario_divergence_status,
            "replay_derived_worst_scenario_divergence_reason": worst_scenario_divergence_reason,
            "replay_derived_worst_scenario_has_output_lineage": worst_scenario_has_output_lineage,
            "replay_output_compared_scenarios": replay_output_compared_scenarios,
            "replay_output_input_trade_rows": cls._safe_int(lineage_summary.get("input_trade_rows", 0)),
            "approval_warning_locked": approval_warning_locked,
            "approval_warning_code": approval_warning_code,
            "approval_warning_message": approval_warning_message,
        }

    @classmethod
    def _apply_true_runner_threshold_lineage_gate(
        cls,
        *,
        recommendation: dict[str, Any],
        true_runner_readiness: dict[str, Any],
        pbo_dsr_metrics: dict[str, Any] | None,
        stress_replay_output_artifacts: dict[str, Any] | None,
        stress_validation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        updated = dict(recommendation)
        base_decision = str(updated.get("decision", "keep_approximation"))
        base_reason = str(updated.get("reason", "not_available"))
        gate_applied = base_decision in cls._REPLACEMENT_DECISIONS

        metrics_payload = dict(pbo_dsr_metrics or {})
        lineage_audit = dict(metrics_payload.get("lineage_audit") or {})
        pbo_recommendation = dict(metrics_payload.get("deployment_recommendation") or {})
        metrics_complete = bool(metrics_payload.get("metrics_complete", False))
        meets_protocol_gate = bool(pbo_recommendation.get("meets_protocol_gate", False))
        true_runner_ready = bool(true_runner_readiness.get("true_runner_ready", False))

        selected_trial_writer_source = str(lineage_audit.get("selected_trial_writer_source", "unknown"))
        selected_trial_selection_rule = str(lineage_audit.get("selected_trial_selection_rule", ""))
        selected_trial_from_runtime_proxy = bool(lineage_audit.get("selected_trial_from_runtime_proxy", False))
        selected_trial_from_true_threshold = bool(lineage_audit.get("selected_trial_from_true_threshold", False))
        threshold_lineage_audit_status = str(
            lineage_audit.get("audit_status", "not_available" if not metrics_payload else "WARN")
        )
        threshold_lineage_audit_reason = str(lineage_audit.get("reason", "not_available"))
        replay_output_lineage_alignment = cls._replay_output_lineage_alignment(
            stress_replay_output_artifacts=stress_replay_output_artifacts,
            pbo_dsr_metrics=pbo_dsr_metrics,
        )
        approval_cross_display = cls._approval_cross_display(
            stress_validation=stress_validation,
            stress_replay_output_artifacts=stress_replay_output_artifacts,
            pbo_dsr_metrics=pbo_dsr_metrics,
        )

        promotion_ready = False
        promotion_status = "NOT_APPLICABLE"
        promotion_reason = base_reason
        promotion_action = "keep_current_path"
        promotion_blocked_by: list[str] = []
        promotion_next_steps: list[str] = []

        if gate_applied:
            if not true_runner_ready:
                promotion_status = "BLOCKED"
                promotion_reason = "true_runner_readiness_not_met"
                promotion_action = "stay_on_prototype"
                promotion_blocked_by.extend([str(item) for item in true_runner_readiness.get("blocked_by", [])])
                promotion_next_steps.extend([str(item) for item in true_runner_readiness.get("next_steps", [])])
            elif not metrics_complete:
                promotion_status = "BLOCKED"
                promotion_reason = "pbo_dsr_metrics_incomplete"
                promotion_action = "stay_on_prototype"
                promotion_blocked_by.append("pbo_dsr_metrics_incomplete")
                promotion_next_steps.append("complete PBO/DSR metrics before promoting the true market replay runner")
            elif not meets_protocol_gate:
                promotion_status = "BLOCKED"
                promotion_reason = "pbo_dsr_protocol_gate_not_met"
                promotion_action = "stay_on_prototype"
                promotion_blocked_by.append("pbo_dsr_protocol_gate_not_met")
                promotion_next_steps.append("raise the selected threshold lineage trial above the PBO/DSR protocol gate")
            elif (
                bool(replay_output_lineage_alignment.get("gate_applied", False))
                and str(replay_output_lineage_alignment.get("status", "NOT_AVAILABLE")) == "WARN"
            ):
                promotion_status = "BLOCKED"
                promotion_reason = (
                    "replay_output_lineage_alignment:"
                    f"{replay_output_lineage_alignment.get('reason', 'not_available')}"
                )
                promotion_action = "stay_on_prototype"
                promotion_blocked_by.append("replay_output_lineage_alignment_warn")
                promotion_next_steps.append(
                    "align replay output lineage with the selected true-threshold winner before promoting the true market replay runner"
                )
            elif threshold_lineage_audit_status != "PASS":
                promotion_status = "BLOCKED"
                promotion_reason = f"threshold_lineage_audit:{threshold_lineage_audit_reason}"
                promotion_action = "stay_on_prototype"
                promotion_blocked_by.append("threshold_lineage_audit_not_pass")
                promotion_next_steps.append("resolve proxy-vs-threshold lineage audit before promoting the true market replay runner")
            elif not selected_trial_from_true_threshold:
                promotion_status = "BLOCKED"
                promotion_reason = "selected_trial_not_from_true_threshold"
                promotion_action = "stay_on_prototype"
                promotion_blocked_by.append("selected_trial_not_from_true_threshold")
                promotion_next_steps.append("select a true-threshold lineage trial before promoting the true market replay runner")
            else:
                promotion_ready = True
                promotion_status = "PASS"
                promotion_reason = "true_runner_and_threshold_lineage_ready"
                promotion_action = "promote_true_market_runner"

        updated["baseline_decision"] = base_decision
        updated["baseline_reason"] = base_reason
        updated["true_runner_promotion_gate_applied"] = gate_applied
        updated["true_runner_promotion_ready"] = promotion_ready
        updated["true_runner_promotion_status"] = promotion_status
        updated["true_runner_promotion_action"] = promotion_action
        updated["true_runner_promotion_reason"] = promotion_reason
        updated["threshold_lineage_audit_status"] = threshold_lineage_audit_status
        updated["threshold_lineage_audit_reason"] = threshold_lineage_audit_reason
        updated["selected_trial_writer_source"] = selected_trial_writer_source
        updated["selected_trial_selection_rule"] = selected_trial_selection_rule
        updated["selected_trial_from_runtime_proxy"] = selected_trial_from_runtime_proxy
        updated["selected_trial_from_true_threshold"] = selected_trial_from_true_threshold
        updated["replay_output_lineage_gate_applied"] = bool(replay_output_lineage_alignment.get("gate_applied", False))
        updated["replay_output_lineage_alignment_status"] = replay_output_lineage_alignment.get("status", "NOT_AVAILABLE")
        updated["replay_output_lineage_alignment_reason"] = replay_output_lineage_alignment.get("reason", "not_available")
        updated["replay_output_lineage_scenarios_compared"] = replay_output_lineage_alignment.get("scenarios_compared", 0)
        updated["replay_output_lineage_compared_scenarios"] = replay_output_lineage_alignment.get("compared_scenarios", [])
        updated["replay_output_lineage_worker_modes"] = replay_output_lineage_alignment.get("worker_modes", [])
        updated["replay_output_lineage_input_batch_count"] = replay_output_lineage_alignment.get("input_batch_count", 0)
        updated["replay_output_lineage_input_trade_rows"] = replay_output_lineage_alignment.get("input_trade_rows", 0)
        updated["pbo_dsr_metrics_complete"] = metrics_complete
        updated["pbo_dsr_meets_protocol_gate"] = meets_protocol_gate
        updated["true_runner_promotion_blocked_by"] = list(dict.fromkeys(promotion_blocked_by))
        updated["true_runner_promotion_next_steps"] = list(dict.fromkeys(promotion_next_steps))
        updated["approval_cross_display"] = approval_cross_display
        return updated

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_stress_replay_assessment_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        coverage = dict(payload.get("coverage") or {})
        readiness = dict(payload.get("readiness_gates") or {})
        recommendation = dict(payload.get("deployment_recommendation") or {})
        scenario_evidence = dict(payload.get("scenario_evidence") or {})
        true_runner_readiness = dict(payload.get("true_runner_readiness") or {})
        true_runner_gates = dict(true_runner_readiness.get("gates") or {})
        lines = [
            f"# Strategy v2 Stress Replay Assessment: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- reason: {payload['reason']}",
            f"- evaluation_basis: {payload.get('evaluation_basis', 'strategy_v2_stress_validation_v2')}",
            "",
            "## Coverage",
            f"- eligible_closed_trades: {int((payload.get('sample_counts') or {}).get('eligible_closed_trades', 0))}",
            f"- execution_fill_coverage: {float(coverage.get('execution_fill_coverage', 0.0)):.4f}",
            f"- estimate_only_share: {float(coverage.get('estimate_only_share', 0.0)):.4f}",
            f"- latency_candle_coverage: {float(coverage.get('latency_candle_coverage', 0.0)):.4f}",
            f"- candle_path_coverage: {float(coverage.get('candle_path_coverage', 0.0)):.4f}",
            f"- latency_fallback_share: {float(coverage.get('latency_fallback_share', 0.0)):.4f}",
            f"- shock_regime_trade_share: {float(coverage.get('shock_regime_trade_share', 0.0)):.4f}",
            "",
            "## Readiness Gates",
            f"- full_replay_ready: {payload.get('full_replay_ready', False)}",
            f"- min_sample_size: {int(readiness.get('min_sample_size', self._MIN_SAMPLE_SIZE))}",
            (
                f"- min_execution_fill_coverage: "
                f"{float(readiness.get('min_execution_fill_coverage', self.settings.stress_replay_lineage_min_execution_fill_coverage)):.2f}"
            ),
            (
                f"- min_latency_candle_coverage: "
                f"{float(readiness.get('min_latency_candle_coverage', self.settings.stress_replay_lineage_min_latency_candle_coverage)):.2f}"
            ),
            "",
            "## Scenario Evidence",
            f"- degraded_scenarios: {scenario_evidence.get('degraded_scenarios', [])}",
            f"- catastrophic_scenarios: {scenario_evidence.get('catastrophic_scenarios', [])}",
            f"- worst_scenario: {scenario_evidence.get('worst_scenario', 'stressed_cost')}",
            f"- scenario_statuses: {scenario_evidence.get('scenario_statuses', {})}",
            "",
            "## Deployment Recommendation",
            f"- replacement_recommended: {payload.get('replacement_recommended', False)}",
            f"- decision: {recommendation.get('decision', 'keep_approximation')}",
            f"- priority: {recommendation.get('priority', 'low')}",
            f"- reason: {recommendation.get('reason', 'not_available')}",
            f"- true_runner_promotion_gate_applied: {bool(recommendation.get('true_runner_promotion_gate_applied', False))}",
            f"- true_runner_promotion_ready: {bool(recommendation.get('true_runner_promotion_ready', False))}",
            f"- true_runner_promotion_status: {recommendation.get('true_runner_promotion_status', 'NOT_APPLICABLE')}",
            f"- true_runner_promotion_action: {recommendation.get('true_runner_promotion_action', 'keep_current_path')}",
            f"- true_runner_promotion_reason: {recommendation.get('true_runner_promotion_reason', 'not_available')}",
            f"- threshold_lineage_audit_status: {recommendation.get('threshold_lineage_audit_status', 'not_available')}",
            f"- threshold_lineage_audit_reason: {recommendation.get('threshold_lineage_audit_reason', 'not_available')}",
            f"- selected_trial_writer_source: {recommendation.get('selected_trial_writer_source', 'unknown')}",
            f"- selected_trial_selection_rule: {recommendation.get('selected_trial_selection_rule', '')}",
            f"- replay_output_lineage_alignment_status: {recommendation.get('replay_output_lineage_alignment_status', 'NOT_AVAILABLE')}",
            f"- replay_output_lineage_alignment_reason: {recommendation.get('replay_output_lineage_alignment_reason', 'not_available')}",
            f"- replay_output_lineage_compared_scenarios: {recommendation.get('replay_output_lineage_compared_scenarios', [])}",
            f"- replay_output_lineage_worker_modes: {recommendation.get('replay_output_lineage_worker_modes', [])}",
            (
                f"- replay_output_lineage_input_batch_count: {int(recommendation.get('replay_output_lineage_input_batch_count', 0) or 0)}, "
                f"input_trade_rows: {int(recommendation.get('replay_output_lineage_input_trade_rows', 0) or 0)}"
            ),
            f"- approval_cross_display: {recommendation.get('approval_cross_display', {})}",
            "",
            "## True Runner Readiness",
            f"- true_runner_ready: {bool(true_runner_readiness.get('true_runner_ready', False))}",
            f"- stage: {true_runner_readiness.get('stage', 'prototype_only')}",
            f"- critical_scenarios: {true_runner_readiness.get('critical_scenarios', [])}",
            f"- critical_scenarios_with_outputs: {true_runner_readiness.get('critical_scenarios_with_outputs', [])}",
            f"- prototype_output_available_scenarios: {true_runner_readiness.get('prototype_output_available_scenarios', [])}",
            f"- scenarios_compared: {int(true_runner_readiness.get('scenarios_compared', 0) or 0)}",
            (
                f"- true_runner_gate_thresholds: exec={float(true_runner_gates.get('min_execution_fill_coverage', 0.0)):.2f}, "
                f"latency={float(true_runner_gates.get('min_latency_candle_coverage', 0.0)):.2f}, "
                f"path={float(true_runner_gates.get('min_candle_path_coverage', 0.0)):.2f}, "
                f"scenarios={int(true_runner_gates.get('min_scenarios_compared', 0) or 0)}"
            ),
            "",
            "## Approximation Limits",
        ]
        for item in payload.get("approximation_limits", []):
            lines.append(f"- {item}")
        lines.extend(["", "## Blockers"])
        for item in payload.get("blocked_by", []):
            lines.append(f"- {item}")
        lines.extend(["", "## Next Steps"])
        for item in payload.get("next_steps", []):
            lines.append(f"- {item}")
        lines.extend(
            [
                "",
                "## Notes",
                "- This artifact evaluates whether the current stress approximation should remain or be replaced by full replay.",
                "- It does not implement counterfactual order-book replay yet.",
                "",
            ]
        )
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def generate(
        self,
        *,
        symbol: str,
        version: str,
        stress_validation: dict[str, Any],
        stress_replay_lineage: dict[str, Any] | None = None,
        stress_replay_output_artifacts: dict[str, Any] | None = None,
        pbo_dsr_metrics: dict[str, Any] | None = None,
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        stress_validation = dict(stress_validation or {})
        stress_replay_lineage = dict(stress_replay_lineage or {})
        stress_replay_output_artifacts = dict(stress_replay_output_artifacts or {})
        sample_counts = dict(stress_validation.get("sample_counts") or {})
        lineage_sample_counts = dict(stress_replay_lineage.get("sample_counts") or {})
        lineage_coverage = dict(stress_replay_lineage.get("coverage") or {})
        eligible_closed_trades = self._safe_int(
            lineage_sample_counts.get("eligible_closed_trades", sample_counts.get("eligible_closed_trades", 0))
        )
        execution_data_trades = self._safe_int(
            lineage_sample_counts.get("full_fill_path_trades", sample_counts.get("execution_data_trades", 0))
        )
        estimate_only_trades = self._safe_int(
            lineage_sample_counts.get("estimate_only_trades", sample_counts.get("estimate_only_trades", 0))
        )
        latency_reference_trades = self._safe_int(
            lineage_sample_counts.get("latency_bar_trades", sample_counts.get("latency_reference_trades", 0))
        )
        shock_regime_trades = self._safe_int(sample_counts.get("shock_regime_trades", 0))
        latency_source_counts = dict(stress_validation.get("latency_source_counts") or {})
        candle_latency_hits = self._candle_latency_hits(latency_source_counts)
        fallback_latency_hits = self._fallback_latency_hits(latency_source_counts)
        scenario_statuses = self._scenario_statuses(stress_validation)
        degraded_scenarios = [
            name for name, row in scenario_statuses.items() if str(row.get("status", "PASS")) != "PASS"
        ]
        catastrophic_scenarios = [
            name for name, row in scenario_statuses.items() if bool(row.get("catastrophic_loss_detected", False))
        ]
        execution_fill_coverage = self._safe_float(
            lineage_coverage.get("execution_fill_coverage"),
            self._ratio(execution_data_trades, eligible_closed_trades),
        )
        estimate_only_share = self._safe_float(
            lineage_coverage.get("estimate_only_share"),
            self._ratio(estimate_only_trades, eligible_closed_trades),
        )
        latency_candle_coverage = self._safe_float(
            lineage_coverage.get("latency_candle_coverage"),
            self._ratio(candle_latency_hits, max(eligible_closed_trades, latency_reference_trades)),
        )
        latency_fallback_share = self._ratio(fallback_latency_hits, max(eligible_closed_trades, latency_reference_trades))
        shock_regime_trade_share = self._ratio(shock_regime_trades, eligible_closed_trades)
        candle_path_coverage = self._safe_float(lineage_coverage.get("candle_path_coverage", 0.0))
        lineage_contract = dict(stress_replay_lineage.get("lineage_contract") or {})
        min_execution_fill_coverage = self._safe_float(
            lineage_contract.get("min_execution_fill_coverage"),
            self._safe_float(self.settings.stress_replay_lineage_min_execution_fill_coverage, 0.70),
        )
        min_latency_candle_coverage = self._safe_float(
            lineage_contract.get("min_latency_candle_coverage"),
            self._safe_float(self.settings.stress_replay_lineage_min_latency_candle_coverage, 0.70),
        )

        full_replay_ready, replacement_recommended, decision, reason, blocked_by, next_steps = self._decision(
            eligible_closed_trades=eligible_closed_trades,
            execution_fill_coverage=execution_fill_coverage,
            latency_candle_coverage=latency_candle_coverage,
            min_execution_fill_coverage=min_execution_fill_coverage,
            min_latency_candle_coverage=min_latency_candle_coverage,
            degraded_scenarios=degraded_scenarios,
            catastrophic_scenarios=catastrophic_scenarios,
        )
        if stress_replay_lineage.get("available"):
            lineage_blockers = [str(item) for item in stress_replay_lineage.get("blocked_by", [])]
            blocked_by = list(dict.fromkeys(lineage_blockers + blocked_by))
            next_steps = list(dict.fromkeys([*(stress_replay_lineage.get("next_steps") or []), *next_steps]))
        priority = "high" if decision == "recommend_full_replay" else "medium" if decision == "prepare_full_replay" else "low"
        worst_scenario = dict(stress_validation.get("deployment_recommendation") or {}).get("worst_scenario", "stressed_cost")
        true_runner_readiness = self._true_runner_readiness(
            full_replay_ready=full_replay_ready,
            replacement_recommended=replacement_recommended,
            execution_fill_coverage=execution_fill_coverage,
            latency_candle_coverage=latency_candle_coverage,
            candle_path_coverage=candle_path_coverage,
            degraded_scenarios=degraded_scenarios,
            catastrophic_scenarios=catastrophic_scenarios,
            worst_scenario=str(worst_scenario),
            stress_replay_output_artifacts=stress_replay_output_artifacts,
        )
        deployment_recommendation = self._apply_true_runner_threshold_lineage_gate(
            recommendation={
                "decision": decision,
                "priority": priority,
                "reason": reason,
            },
            true_runner_readiness=true_runner_readiness,
            pbo_dsr_metrics=pbo_dsr_metrics,
            stress_replay_output_artifacts=stress_replay_output_artifacts,
            stress_validation=stress_validation,
        )

        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_stress_replay_assessment_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": bool(stress_validation.get("available", False)),
            "reason": reason if eligible_closed_trades > 0 else "no_closed_v2_trades",
            "evaluation_basis": (
                f"{stress_validation.get('schema_version', 'strategy_v2_stress_validation_v2')} + "
                f"{stress_replay_lineage.get('schema_version', 'strategy_v2_stress_replay_lineage_v1')}"
                if stress_replay_lineage
                else str(stress_validation.get("schema_version", "strategy_v2_stress_validation_v2"))
            ),
            "full_replay_ready": full_replay_ready,
            "replacement_recommended": replacement_recommended,
            "sample_counts": {
                "eligible_closed_trades": eligible_closed_trades,
                "execution_data_trades": execution_data_trades,
                "estimate_only_trades": estimate_only_trades,
                "latency_reference_trades": latency_reference_trades,
                "shock_regime_trades": shock_regime_trades,
            },
            "coverage": {
                "execution_fill_coverage": execution_fill_coverage,
                "estimate_only_share": estimate_only_share,
                "latency_candle_coverage": latency_candle_coverage,
                "candle_path_coverage": candle_path_coverage,
                "latency_fallback_share": latency_fallback_share,
                "shock_regime_trade_share": shock_regime_trade_share,
            },
            "readiness_gates": {
                "min_sample_size": self._MIN_SAMPLE_SIZE,
                "min_execution_fill_coverage": min_execution_fill_coverage,
                "min_latency_candle_coverage": min_latency_candle_coverage,
            },
            "scenario_evidence": {
                "degraded_scenarios": degraded_scenarios,
                "catastrophic_scenarios": catastrophic_scenarios,
                "worst_scenario": worst_scenario,
                "scenario_statuses": scenario_statuses,
                "lineage_runtime_inputs_ready": bool(stress_replay_lineage.get("runtime_inputs_ready", False))
                if stress_replay_lineage
                else None,
            },
            "approximation_limits": [
                "saved closed-v2 realized R is the starting point instead of intrabar execution replay",
                "partial fills only uses a fixed 50% fill factor",
                "latency +1 bar uses the next 5m candle open, not order-book path replay",
                "shock concentration uses heuristic loss amplification / upside compression",
                "missing execution fills fall back to plan.cost_est decomposition",
            ],
            "blocked_by": blocked_by,
            "next_steps": next_steps,
            "true_runner_readiness": true_runner_readiness,
            "deployment_recommendation": deployment_recommendation,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
