from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.edge_experiment_review import (
    build_edge_experiment_review,
    summarize_edge_experiment_review,
)
from app.services.edge_evolution_rule import build_edge_evolution_rule, summarize_edge_evolution_rule
from app.services.outcome_attribution import build_outcome_attribution, summarize_outcome_attribution
from app.services.outcome_control_trace import (
    build_outcome_control_trace,
    summarize_outcome_control_trace,
)
from app.services.outcome_funnel_operating_kpis import build_outcome_funnel_operating_kpis
from app.services.split_review_followup_ledger import summarize_split_review_followup_ledger


class ValidationReportService:
    def __init__(self):
        self.settings = get_settings()

    @staticmethod
    def _split_review_followup_command(*, action: str, symbol: str, universe: str, days: int) -> str:
        if action not in {"run_entry_timing_split_review", "run_execution_style_split_review"} or not symbol:
            return ""
        return (
            f"./.venv/bin/python scripts/run_split_review_followup.py "
            f"--symbol {symbol.upper()} --universe {universe} --days {max(int(days), 1)} --action {action}"
        )

    @classmethod
    def _normalize_operator_action_priority_payload(
        cls,
        payload: dict[str, Any] | None,
        *,
        symbol: str,
        universe: str,
        days: int,
    ) -> dict[str, Any]:
        priority = dict(payload or {})
        if not priority:
            return {}

        experiment_context = dict(priority.get("experiment_context") or {})
        target_specs = (
            ("entry_timing_target", "run_entry_timing_split_review"),
            ("execution_style_target", "run_execution_style_split_review"),
        )
        for key, action in target_specs:
            target = dict(experiment_context.get(key) or {})
            target_symbol = str(target.get("symbol") or symbol or "")
            if target and not target.get("followup_command"):
                target["followup_command"] = cls._split_review_followup_command(
                    action=action,
                    symbol=target_symbol,
                    universe=universe,
                    days=max(int(days), 1),
                )
                experiment_context[key] = target
        if experiment_context:
            priority["experiment_context"] = experiment_context

        normalized_actions: list[dict[str, Any]] = []
        for row in list(priority.get("next_actions") or []):
            item = dict(row or {})
            if not item.get("followup_command"):
                item["followup_command"] = cls._split_review_followup_command(
                    action=str(item.get("action") or ""),
                    symbol=str(item.get("target_symbol") or symbol or ""),
                    universe=universe,
                    days=max(int(days), 1),
                )
            normalized_actions.append(item)
        priority["next_actions"] = normalized_actions

        if not priority.get("top_action_followup_command"):
            top_action = str(priority.get("top_action") or "")
            top_target_key = {
                "run_entry_timing_split_review": "entry_timing_target",
                "run_execution_style_split_review": "execution_style_target",
            }.get(top_action, "")
            top_target = dict(experiment_context.get(top_target_key) or {})
            priority["top_action_followup_command"] = cls._split_review_followup_command(
                action=top_action,
                symbol=str(top_target.get("symbol") or symbol or ""),
                universe=universe,
                days=max(int(days), 1),
            )
        return priority

    @staticmethod
    def _approval_warning_playbook_mapping(
        *,
        approval_warning_locked: bool,
        approval_warning_code: str,
        topline_status: str,
    ) -> dict[str, str]:
        if approval_warning_locked:
            mapping = {
                "proxy_selected_trial_against_replay_backed_worst_scenario": {
                    "playbook_go_no_go": "NO_GO",
                    "playbook_code": "no_go_proxy_selected_trial_against_replay_backed_worst_scenario",
                    "playbook_action": "hold_live_rollout_and_keep_prototype_path",
                    "playbook_message": (
                        "NO-GO: runtime proxy selected-trial is still active while replay-backed downside is worse. "
                        "Keep rollout blocked and do not treat this setup as threshold-lineage confirmed."
                    ),
                },
                "threshold_lineage_winner_unresolved": {
                    "playbook_go_no_go": "NO_GO",
                    "playbook_code": "no_go_threshold_lineage_winner_unresolved",
                    "playbook_action": "resolve_selected_trial_lineage_before_rollout",
                    "playbook_message": (
                        "NO-GO: selected-trial lineage winner is unresolved. "
                        "Resolve threshold lineage first, then rerun approval."
                    ),
                },
                "replay_backed_worst_scenario_missing": {
                    "playbook_go_no_go": "NO_GO",
                    "playbook_code": "no_go_replay_backed_worst_scenario_missing",
                    "playbook_action": "wait_for_replay_backed_downside_evidence",
                    "playbook_message": (
                        "NO-GO: worst downside scenario is not replay-backed yet. "
                        "Keep approval blocked until replay-backed downside evidence exists."
                    ),
                },
            }
            return dict(
                mapping.get(
                    approval_warning_code,
                    {
                        "playbook_go_no_go": "NO_GO",
                        "playbook_code": "no_go_unknown_approval_warning",
                        "playbook_action": "hold_rollout_and_review_warning_contract",
                        "playbook_message": (
                            "NO-GO: approval template emitted an unknown warning code. "
                            "Review the warning contract before any rollout."
                        ),
                    },
                )
            )
        if topline_status == "PASS":
            return {
                "playbook_go_no_go": "GO",
                "playbook_code": "go_approval_template_aligned",
                "playbook_action": "proceed_with_configured_rollout",
                "playbook_message": (
                    "GO: approval template is aligned with replay-backed downside and the current threshold-lineage winner."
                ),
            }
        if topline_status == "REVIEW":
            return {
                "playbook_go_no_go": "MANUAL_REVIEW",
                "playbook_code": "manual_review_alignment_warning",
                "playbook_action": "hold_rollout_and_review_alignment_details",
                "playbook_message": (
                    "MANUAL REVIEW: alignment warning remains. Hold rollout until the approval template warning is cleared."
                ),
            }
        return {
            "playbook_go_no_go": "NO_GO",
            "playbook_code": "no_go_approval_template_unavailable",
            "playbook_action": "block_rollout_until_template_available",
            "playbook_message": (
                "NO-GO: approval template is unavailable. Do not proceed until validation summary is generated."
            ),
        }

    @staticmethod
    def _overall_status(wf: dict[str, Any], mc: dict[str, Any], metric: dict[str, Any]) -> str:
        checks = [
            wf.get("mean_ev", 0.0) > 0,
            wf.get("p5_ev", -99.0) > -0.8,
            mc.get("p5_ev", -99.0) > -0.6,
            metric.get("ev", -99.0) > 0,
        ]
        passed = sum(1 for x in checks if x)
        if passed == len(checks):
            return "PASS"
        if passed >= 2:
            return "WARN"
        return "FAIL"

    @staticmethod
    def _approval_strip_summary(
        *,
        deployment_approval_template: dict[str, Any] | None,
        operator_action_priority_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        template = dict(deployment_approval_template or {})
        if not template and not operator_action_priority_summary:
            return None

        playbook_go_no_go = str(template.get("playbook_go_no_go") or "")
        playbook_action = str(template.get("playbook_action") or "")
        playbook_message = str(template.get("playbook_message") or "")
        topline_message = str(template.get("topline_message") or "")
        template_status = str(template.get("template_status") or "NOT_AVAILABLE")
        replay_alignment_status = str(template.get("replay_output_lineage_alignment_status") or "NOT_AVAILABLE")
        approval_warning_locked = bool(template.get("approval_warning_locked", False))
        priority = dict(operator_action_priority_summary or {})

        approve_value = "approval usable"
        if playbook_go_no_go == "NO_GO":
            approve_value = "validation no_go"
        elif playbook_go_no_go == "MANUAL_REVIEW":
            approve_value = "manual review first"
        approve_reason = playbook_message or topline_message or "validation approval strip unavailable"

        if not template:
            align_value = "not_available"
            align_reason = "deployment approval template unavailable"
        elif approval_warning_locked or replay_alignment_status == "WARN" or template_status == "REVIEW":
            align_value = "playbook_drift"
            align_reason = " | ".join(
                part
                for part in [
                    template.get("approval_warning_message"),
                    f"template_status={template_status}",
                    f"replay_alignment={replay_alignment_status}",
                    template.get("template_reason"),
                ]
                if part
            )
        elif template_status == "PASS":
            align_value = "aligned"
            align_reason = " | ".join(
                part
                for part in [
                    template.get("topline_summary_line"),
                    template.get("template_reason"),
                ]
                if part
            ) or "validation approval template is aligned"
        else:
            align_value = "not_available"
            align_reason = " | ".join(
                part
                for part in [
                    f"template_status={template_status}",
                    template.get("template_reason"),
                ]
                if part
            ) or "validation approval alignment unavailable"

        act_value = str(priority.get("top_action") or playbook_action or "continue_runtime_monitoring")
        act_reason = str(
            priority.get("top_reason")
            or playbook_message
            or topline_message
            or "validation operator action unavailable"
        )
        next_actions = [dict(item) for item in list(priority.get("next_actions") or [])[:3]]
        if next_actions:
            act_reason = f"{act_reason} | " + " | ".join(
                f"{item.get('action')} [{item.get('priority_level')}]"
                for item in next_actions
                if item.get("action")
            )

        return {
            "available": True,
            "approve_value": approve_value,
            "approve_reason": approve_reason,
            "align_value": align_value,
            "align_reason": align_reason,
            "act_value": act_value,
            "act_reason": act_reason,
            "act_priority_level": str(priority.get("priority_level") or "monitor"),
        }

    @staticmethod
    def _deployment_approval_template(
        *,
        pbo_dsr_metrics_payload: dict[str, Any],
        stress_payload: dict[str, Any],
        stress_replay_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not pbo_dsr_metrics_payload and not stress_payload and not stress_replay_payload:
            return None

        pbo_selected_trial = dict(pbo_dsr_metrics_payload.get("selected_trial") or {})
        pbo_lineage_audit = dict(pbo_dsr_metrics_payload.get("lineage_audit") or {})
        stress_recommendation = dict(stress_payload.get("deployment_recommendation") or {})
        stress_replay_recommendation = dict(stress_replay_payload.get("deployment_recommendation") or {})
        approval_cross_display = dict(stress_replay_recommendation.get("approval_cross_display") or {})

        threshold_lineage_winner_source = str(
            approval_cross_display.get("threshold_lineage_winner_source")
            or pbo_selected_trial.get("writer_source")
            or pbo_lineage_audit.get("selected_trial_writer_source", "unknown")
        )
        threshold_lineage_winner_selection_rule = str(
            approval_cross_display.get("threshold_lineage_winner_selection_rule")
            or pbo_selected_trial.get("selection_rule")
            or pbo_lineage_audit.get("selected_trial_selection_rule", "")
        )
        threshold_lineage_winner_type = str(
            approval_cross_display.get("threshold_lineage_winner_type")
            or (
                "true_threshold"
                if pbo_lineage_audit.get("selected_trial_from_true_threshold", False)
                else "runtime_proxy"
                if pbo_lineage_audit.get("selected_trial_from_runtime_proxy", False)
                else "unresolved"
            )
        )
        replay_derived_worst_scenario = str(
            approval_cross_display.get("replay_derived_worst_scenario")
            or stress_recommendation.get("worst_scenario", "stressed_cost")
        )
        replay_derived_worst_scenario_source = str(
            approval_cross_display.get("replay_derived_worst_scenario_source")
            or stress_recommendation.get("worst_scenario_source", "stressed_cost")
        )
        replay_derived_worst_scenario_status = str(
            approval_cross_display.get("replay_derived_worst_scenario_status")
            or dict((stress_recommendation.get("scenario_statuses") or {})).get(replay_derived_worst_scenario, {}).get(
                "status", "NOT_AVAILABLE"
            )
        )
        replay_derived_worst_scenario_reason = str(
            approval_cross_display.get("replay_derived_worst_scenario_reason")
            or dict((stress_recommendation.get("scenario_statuses") or {})).get(replay_derived_worst_scenario, {}).get(
                "reason", stress_recommendation.get("reason", "not_available")
            )
        )
        template_status = str(approval_cross_display.get("cross_display_status", "NOT_AVAILABLE"))
        template_reason = str(approval_cross_display.get("cross_display_reason", "approval_cross_display_unavailable"))
        replay_alignment_status = str(
            stress_replay_recommendation.get("replay_output_lineage_alignment_status", "NOT_AVAILABLE")
        )
        replay_alignment_reason = str(
            stress_replay_recommendation.get("replay_output_lineage_alignment_reason", "not_available")
        )
        approval_warning_locked = bool(approval_cross_display.get("approval_warning_locked", False))
        approval_warning_code = str(approval_cross_display.get("approval_warning_code", "none"))
        approval_warning_message = str(
            approval_cross_display.get("approval_warning_message", "approval_template_cross_display_is_consistent")
        )
        true_runner_promotion_action = str(
            stress_replay_recommendation.get("true_runner_promotion_action", "keep_current_path")
        )
        topline_summary_line = (
            f"winner={threshold_lineage_winner_type}/{threshold_lineage_winner_source}; "
            f"worst={replay_derived_worst_scenario}/{replay_derived_worst_scenario_status}/{replay_derived_worst_scenario_source}; "
            f"promotion={true_runner_promotion_action}"
        )
        if replay_alignment_status == "WARN":
            topline_status = "REVIEW"
            topline_code = approval_warning_code if approval_warning_locked else "replay_output_lineage_alignment_warning"
            topline_message = ""
        elif replay_alignment_status == "PASS" and template_status == "PASS":
            topline_status = "PASS"
            topline_code = "approval_template_aligned"
            topline_message = ""
        elif template_status == "REVIEW":
            topline_status = "REVIEW"
            topline_code = template_reason
            topline_message = ""
        elif template_status == "PASS":
            topline_status = "PASS"
            topline_code = "approval_template_ready"
            topline_message = ""
        else:
            topline_status = "NOT_AVAILABLE"
            topline_code = "approval_template_unavailable"
            topline_message = ""
        playbook_mapping = ValidationReportService._approval_warning_playbook_mapping(
            approval_warning_locked=approval_warning_locked,
            approval_warning_code=approval_warning_code,
            topline_status=topline_status,
        )
        go_no_go = playbook_mapping["playbook_go_no_go"]
        playbook_message = playbook_mapping["playbook_message"]
        if go_no_go == "GO":
            topline_message = f"GO: {playbook_message} {topline_summary_line}."
        elif go_no_go == "MANUAL_REVIEW":
            topline_message = f"MANUAL_REVIEW: {playbook_message} {topline_summary_line}."
        else:
            topline_message = f"NO_GO: {playbook_message} {topline_summary_line}."
        return {
            "topline_status": topline_status,
            "topline_code": topline_code,
            "topline_message": topline_message,
            "topline_summary_line": topline_summary_line,
            "playbook_go_no_go": playbook_mapping["playbook_go_no_go"],
            "playbook_code": playbook_mapping["playbook_code"],
            "playbook_action": playbook_mapping["playbook_action"],
            "playbook_message": playbook_mapping["playbook_message"],
            "template_status": template_status,
            "template_reason": template_reason,
            "threshold_lineage_winner_source": threshold_lineage_winner_source,
            "threshold_lineage_winner_selection_rule": threshold_lineage_winner_selection_rule,
            "threshold_lineage_winner_type": threshold_lineage_winner_type,
            "threshold_lineage_audit_status": str(
                approval_cross_display.get("threshold_lineage_audit_status")
                or pbo_lineage_audit.get("audit_status", "not_available")
            ),
            "replay_derived_worst_scenario": replay_derived_worst_scenario,
            "replay_derived_worst_scenario_source": replay_derived_worst_scenario_source,
            "replay_derived_worst_scenario_status": replay_derived_worst_scenario_status,
            "replay_derived_worst_scenario_reason": replay_derived_worst_scenario_reason,
            "replay_derived_worst_scenario_divergence_status": str(
                approval_cross_display.get("replay_derived_worst_scenario_divergence_status", "NOT_AVAILABLE")
            ),
            "replay_output_compared_scenarios": list(
                approval_cross_display.get("replay_output_compared_scenarios")
                or stress_replay_recommendation.get("replay_output_lineage_compared_scenarios")
                or []
            ),
            "replay_output_input_trade_rows": int(
                approval_cross_display.get("replay_output_input_trade_rows")
                or stress_replay_recommendation.get("replay_output_lineage_input_trade_rows", 0)
                or 0
            ),
            "approval_warning_locked": approval_warning_locked,
            "approval_warning_code": approval_warning_code,
            "approval_warning_message": approval_warning_message,
            "true_runner_promotion_action": true_runner_promotion_action,
            "selected_trial_writer_source": str(
                stress_replay_recommendation.get("selected_trial_writer_source", threshold_lineage_winner_source)
            ),
        }

    @staticmethod
    def _named_bucket(
        metrics: dict[str, dict[str, Any]],
        *,
        metric_key: str,
        sample_key: str = "trades",
        prefer_high: bool = True,
    ) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        for name, payload in sorted((metrics or {}).items()):
            sample_value = int((payload or {}).get(sample_key, 0) or 0)
            if sample_value <= 0:
                continue
            metric_value = round(float((payload or {}).get(metric_key, 0.0) or 0.0), 4)
            candidates.append(
                {
                    "name": str(name),
                    metric_key: metric_value,
                    sample_key: sample_value,
                }
            )
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                float(item.get(metric_key, 0.0)) if prefer_high else -float(item.get(metric_key, 0.0)),
                int(item.get(sample_key, 0)),
                str(item.get("name", "")),
            ),
        )

    @classmethod
    def _entry_model_summary(cls, execution_quality: dict[str, Any]) -> dict[str, Any]:
        by_entry_model = dict(execution_quality.get("by_entry_model") or {})
        normalized: dict[str, dict[str, Any]] = {}
        for name, payload in sorted(by_entry_model.items()):
            plans = int((payload or {}).get("plans", 0) or 0)
            if plans <= 0:
                continue
            fill_rate = round(float((payload or {}).get("fill_rate", 0.0) or 0.0), 4)
            normalized[str(name)] = {
                "plans": plans,
                "fill_rate": fill_rate,
                "unfilled_rate": round(max(0.0, 1.0 - fill_rate), 4),
                "avg_slippage_bps": round(float((payload or {}).get("avg_slippage_bps", 0.0) or 0.0), 4),
                "avg_entry_latency_seconds": round(
                    float((payload or {}).get("avg_entry_latency_seconds", 0.0) or 0.0),
                    4,
                ),
            }
        return {
            "best_fill_rate": cls._named_bucket(normalized, metric_key="fill_rate", sample_key="plans", prefer_high=True),
            "worst_fill_rate": cls._named_bucket(normalized, metric_key="fill_rate", sample_key="plans", prefer_high=False),
            "worst_slippage_bps": cls._named_bucket(
                normalized,
                metric_key="avg_slippage_bps",
                sample_key="plans",
                prefer_high=True,
            ),
            "highest_latency": cls._named_bucket(
                normalized,
                metric_key="avg_entry_latency_seconds",
                sample_key="plans",
                prefer_high=True,
            ),
        }

    @classmethod
    def _performance_decomposition_summary(
        cls,
        *,
        execution_quality: dict[str, Any] | None,
        strategy_v2_validation: dict[str, Any] | None,
        strategy_v2_stress_validation: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        v2_payload = dict(strategy_v2_validation or {})
        execution_payload = dict(execution_quality or {})
        stress_payload = dict(strategy_v2_stress_validation or {})

        family_metrics = dict(v2_payload.get("family_metrics") or {})
        regime_metrics = dict(v2_payload.get("regime_metrics") or {})
        session_metrics = dict(v2_payload.get("session_metrics") or {})
        family_execution = dict(execution_payload.get("by_strategy_family") or {})

        family_summary = {
            "best_ev": cls._named_bucket(family_metrics, metric_key="ev", sample_key="trades", prefer_high=True),
            "worst_ev": cls._named_bucket(family_metrics, metric_key="ev", sample_key="trades", prefer_high=False),
            "highest_forced_exit_rate": cls._named_bucket(
                family_execution,
                metric_key="forced_exit_rate",
                sample_key="closed",
                prefer_high=True,
            ),
            "highest_information_failure_rate": cls._named_bucket(
                family_execution,
                metric_key="information_failure_rate",
                sample_key="closed",
                prefer_high=True,
            ),
            "highest_time_failure_rate": cls._named_bucket(
                family_execution,
                metric_key="time_failure_rate",
                sample_key="closed",
                prefer_high=True,
            ),
        }
        regime_summary = {
            "best_ev": cls._named_bucket(regime_metrics, metric_key="ev", sample_key="trades", prefer_high=True),
            "worst_ev": cls._named_bucket(regime_metrics, metric_key="ev", sample_key="trades", prefer_high=False),
        }
        session_summary = {
            "best_ev": cls._named_bucket(session_metrics, metric_key="ev", sample_key="trades", prefer_high=True),
            "worst_ev": cls._named_bucket(session_metrics, metric_key="ev", sample_key="trades", prefer_high=False),
        }
        entry_model_summary = cls._entry_model_summary(execution_payload) if execution_payload else {}

        stress_metrics = dict(stress_payload.get("stress_metrics") or {})
        baseline_cost = dict(stress_metrics.get("baseline_cost") or {})
        stressed_cost = dict(stress_metrics.get("stressed_cost") or {})
        stress_comparison = dict(stress_payload.get("comparison") or {})
        cost_summary = None
        if stress_payload:
            cost_summary = {
                "baseline_cost_ev": round(float(baseline_cost.get("ev", 0.0) or 0.0), 4),
                "stressed_cost_ev": round(float(stressed_cost.get("ev", 0.0) or 0.0), 4),
                "delta_ev_stressed_minus_baseline": round(float(stress_comparison.get("ev", 0.0) or 0.0), 4),
                "worst_scenario": str(
                    dict(stress_payload.get("deployment_recommendation") or {}).get("worst_scenario", "stressed_cost")
                ),
                "worst_scenario_source": str(
                    dict(stress_payload.get("deployment_recommendation") or {}).get(
                        "worst_scenario_source",
                        "stressed_cost",
                    )
                ),
            }

        tuning_focus: list[dict[str, Any]] = []
        family_info = dict(family_summary.get("highest_information_failure_rate") or {})
        if float(family_info.get("information_failure_rate", 0.0) or 0.0) > 0.0:
            tuning_focus.append(
                {
                    "focus": "family_information_failure",
                    "bucket": family_info.get("name"),
                    "metric": "information_failure_rate",
                    "value": float(family_info.get("information_failure_rate", 0.0) or 0.0),
                    "samples": int(family_info.get("closed", 0) or 0),
                }
            )
        family_forced = dict(family_summary.get("highest_forced_exit_rate") or {})
        if float(family_forced.get("forced_exit_rate", 0.0) or 0.0) > 0.0:
            tuning_focus.append(
                {
                    "focus": "family_forced_exit",
                    "bucket": family_forced.get("name"),
                    "metric": "forced_exit_rate",
                    "value": float(family_forced.get("forced_exit_rate", 0.0) or 0.0),
                    "samples": int(family_forced.get("closed", 0) or 0),
                }
            )
        worst_regime = dict(regime_summary.get("worst_ev") or {})
        if float(worst_regime.get("ev", 0.0) or 0.0) < 0.0:
            tuning_focus.append(
                {
                    "focus": "regime_negative_ev",
                    "bucket": worst_regime.get("name"),
                    "metric": "ev",
                    "value": float(worst_regime.get("ev", 0.0) or 0.0),
                    "samples": int(worst_regime.get("trades", 0) or 0),
                }
            )
        worst_session = dict(session_summary.get("worst_ev") or {})
        if float(worst_session.get("ev", 0.0) or 0.0) < 0.0:
            tuning_focus.append(
                {
                    "focus": "session_negative_ev",
                    "bucket": worst_session.get("name"),
                    "metric": "ev",
                    "value": float(worst_session.get("ev", 0.0) or 0.0),
                    "samples": int(worst_session.get("trades", 0) or 0),
                }
            )
        worst_fill_model = dict((entry_model_summary or {}).get("worst_fill_rate") or {})
        if float(worst_fill_model.get("fill_rate", 1.0) or 1.0) < 1.0:
            tuning_focus.append(
                {
                    "focus": "entry_model_fill_rate",
                    "bucket": worst_fill_model.get("name"),
                    "metric": "fill_rate",
                    "value": float(worst_fill_model.get("fill_rate", 0.0) or 0.0),
                    "samples": int(worst_fill_model.get("plans", 0) or 0),
                }
            )
        worst_slippage_model = dict((entry_model_summary or {}).get("worst_slippage_bps") or {})
        if float(worst_slippage_model.get("avg_slippage_bps", 0.0) or 0.0) > 0.0:
            tuning_focus.append(
                {
                    "focus": "entry_model_slippage",
                    "bucket": worst_slippage_model.get("name"),
                    "metric": "avg_slippage_bps",
                    "value": float(worst_slippage_model.get("avg_slippage_bps", 0.0) or 0.0),
                    "samples": int(worst_slippage_model.get("plans", 0) or 0),
                }
            )
        if cost_summary and float(cost_summary.get("delta_ev_stressed_minus_baseline", 0.0) or 0.0) < 0.0:
            tuning_focus.append(
                {
                    "focus": "post_cost_ev_deterioration",
                    "bucket": cost_summary.get("worst_scenario"),
                    "metric": "delta_ev_stressed_minus_baseline",
                    "value": float(cost_summary.get("delta_ev_stressed_minus_baseline", 0.0) or 0.0),
                    "samples": 0,
                }
            )

        if not any([family_metrics, regime_metrics, session_metrics, family_execution, entry_model_summary, cost_summary]):
            return None

        return {
            "family": family_summary,
            "regime": regime_summary,
            "session": session_summary,
            "entry_model": entry_model_summary,
            "cost": cost_summary,
            "tuning_focus": tuning_focus[:5],
        }

    def generate(
        self,
        *,
        symbol: str,
        version: str,
        wf: dict[str, Any],
        mc: dict[str, Any],
        metric: dict[str, Any],
        execution_quality: dict[str, Any] | None = None,
        execution_friction_measurement: dict[str, Any] | None = None,
        forward_stress_regime_validation: dict[str, Any] | None = None,
        kill_condition_automation: dict[str, Any] | None = None,
        feature_importance: dict[str, Any] | None = None,
        feature_calibration: dict[str, Any] | None = None,
        strategy_v2_validation: dict[str, Any] | None = None,
        strategy_v2_lock_validation: dict[str, Any] | None = None,
        strategy_v2_pbo_dsr_trial_writer: dict[str, Any] | None = None,
        strategy_v2_pbo_dsr_threshold_runner: dict[str, Any] | None = None,
        strategy_v2_pbo_dsr_artifact_store: dict[str, Any] | None = None,
        strategy_v2_pbo_dsr_design: dict[str, Any] | None = None,
        strategy_v2_pbo_dsr_metrics: dict[str, Any] | None = None,
        strategy_v2_stress_validation: dict[str, Any] | None = None,
        strategy_v2_stress_replay_lineage: dict[str, Any] | None = None,
        strategy_v2_stress_replay_assessment: dict[str, Any] | None = None,
        strategy_v2_stress_replay_runner_contract: dict[str, Any] | None = None,
        strategy_v2_stress_replay_lineage_writer: dict[str, Any] | None = None,
        strategy_v2_stress_replay_prototype_worker: dict[str, Any] | None = None,
        strategy_v2_thesis_validation: dict[str, Any] | None = None,
        strategy_v2_scalp_experiment: dict[str, Any] | None = None,
        alpha_research_pipeline: dict[str, Any] | None = None,
        score_to_outcome_funnel: dict[str, Any] | None = None,
        execution_degradation_advisory: dict[str, Any] | None = None,
        family_execution_degradation_advisory: dict[str, Any] | None = None,
        mode_advisory: dict[str, Any] | None = None,
        operator_action_priority: dict[str, Any] | None = None,
        rollout_recommendation: dict[str, Any] | None = None,
        strategy_lifecycle: dict[str, Any] | None = None,
        promotion_governance: dict[str, Any] | None = None,
        promotion_review_queue: dict[str, Any] | None = None,
        promotion_remediation_queue: dict[str, Any] | None = None,
        promotion_clearance_tracker: dict[str, Any] | None = None,
        promotion_reopen_queue: dict[str, Any] | None = None,
        promotion_decision_brief: dict[str, Any] | None = None,
        auto_promotion_rollout_execution: dict[str, Any] | None = None,
        b_continuation_activation: dict[str, Any] | None = None,
        b_continuation_edge_validation: dict[str, Any] | None = None,
        strategy_cluster_balance: dict[str, Any] | None = None,
        a_strategy_post_cost_edge_validation: dict[str, Any] | None = None,
        promotion_lifecycle_history: dict[str, Any] | None = None,
        research_promotion_operating_loop: dict[str, Any] | None = None,
        multi_strategy_ab: dict[str, Any] | None = None,
        positive_evidence_expansion: dict[str, Any] | None = None,
        outcome_bucket_granularity: dict[str, Any] | None = None,
        opportunity_capture: dict[str, Any] | None = None,
        capital_allocator: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        status = self._overall_status(wf=wf, mc=mc, metric=metric)
        file_path = out_dir / f"{symbol}_{version}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"

        fi_available = bool((feature_importance or {}).get("available"))
        fi_ranking = list((feature_importance or {}).get("ranking", []))[:3]
        fi_lines: list[str] = []
        if fi_available:
            fi_lines = [
                "## Feature Importance (Ablation)",
                "- baseline is current feature set; each feature is zeroed independently.",
            ]
            for idx, row in enumerate(fi_ranking, start=1):
                fi_lines.append(
                    f"- top_{idx}: {row.get('feature')} | importance={float(row.get('importance_score', 0.0)):.3f} | "
                    f"delta_ev={float(row.get('delta_mean_ev', 0.0)):.4f} | delta_rank={float(row.get('delta_top_rank_score', 0.0)):.3f}"
                )
            fi_lines.append("")
        else:
            fi_lines = [
                "## Feature Importance (Ablation)",
                f"- unavailable: {(feature_importance or {}).get('reason', 'not_requested')}",
                "",
            ]

        fc_available = bool((feature_calibration or {}).get("available"))
        fc_regime = str((feature_calibration or {}).get("regime_label", "n/a"))
        fc_row = dict(((feature_calibration or {}).get("by_regime") or {}).get(fc_regime, {}))
        fc_base = dict(fc_row.get("feature_weights_base") or (feature_calibration or {}).get("baseline_weights") or {})
        fc_active = dict(fc_row.get("feature_weights_active") or (feature_calibration or {}).get("recommended_weights") or {})
        fc_adjustments = []
        for key, active in fc_active.items():
            base = float(fc_base.get(key, active))
            fc_adjustments.append(
                {
                    "feature": key,
                    "base": base,
                    "active": float(active),
                    "delta": round(float(active) - base, 6),
                }
            )
        fc_adjustments.sort(key=lambda item: abs(float(item["delta"])), reverse=True)
        fc_top_adjustments = fc_adjustments[:3]
        fc_lines: list[str] = []
        if fc_available:
            fc_lines = [
                "## Feature Calibration",
                f"- regime_label: {fc_regime}",
                f"- matched_samples: {(feature_calibration or {}).get('matched_samples', 0)}",
                f"- applied_runtime: {(feature_calibration or {}).get('applied_runtime', False)}",
            ]
            for idx, row in enumerate(fc_top_adjustments, start=1):
                fc_lines.append(
                    f"- top_{idx}: {row['feature']} | base={float(row['base']):.4f} | "
                    f"active={float(row['active']):.4f} | delta={float(row['delta']):+.4f}"
                )
            fc_lines.append("")
        else:
            fc_lines = [
                "## Feature Calibration",
                f"- unavailable: {(feature_calibration or {}).get('reason', 'not_requested')}",
                "",
            ]

        eq_top_reasons = sorted(
            ((execution_quality or {}).get("final_exit_reasons") or {}).items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        )[:3]
        eq_lines: list[str] = []
        if execution_quality:
            eq_lines = [
                "## Exit Quality",
                f"- target_exit_ratio: {float((execution_quality or {}).get('target_exit_ratio', 0.0)):.4f}",
                f"- forced_exit_ratio: {float((execution_quality or {}).get('forced_exit_ratio', 0.0)):.4f}",
                f"- information_failure_ratio: {float((execution_quality or {}).get('information_failure_ratio', 0.0)):.4f}",
                f"- time_failure_ratio: {float((execution_quality or {}).get('time_failure_ratio', 0.0)):.4f}",
            ]
            for idx, (reason, count) in enumerate(eq_top_reasons, start=1):
                eq_lines.append(f"- top_{idx}: {reason} | count={int(count)}")
            eq_lines.append("")

        execution_friction_measurement_payload = dict(execution_friction_measurement or {})
        execution_friction_measurement_lines: list[str] = []
        if execution_friction_measurement_payload:
            source_summary = dict(execution_friction_measurement_payload.get("source_summary") or {})
            execution_friction_measurement_lines = [
                "## Execution Friction Measurement",
                f"- available: {bool(execution_friction_measurement_payload.get('available', False))}",
                f"- advisory_only: {bool(execution_friction_measurement_payload.get('advisory_only', True))}",
                (
                    f"- friction_state: {execution_friction_measurement_payload.get('friction_state', 'insufficient_measurement')} "
                    f"| friction_bias={execution_friction_measurement_payload.get('friction_bias', 'gather_more_execution_evidence')} "
                    f"| confidence={execution_friction_measurement_payload.get('confidence', 'low')}"
                ),
                (
                    f"- fill_conversion_state: {execution_friction_measurement_payload.get('fill_conversion_state', 'healthy_fill_conversion')} "
                    f"| measurement_coverage_state={execution_friction_measurement_payload.get('measurement_coverage_state', 'thin_measurement')}"
                ),
                (
                    f"- slippage_state: {execution_friction_measurement_payload.get('slippage_state', 'healthy_slippage')} "
                    f"| avg_slippage_bps={float(execution_friction_measurement_payload.get('avg_slippage_bps', 0.0) or 0.0):.4f} "
                    f"| p95_slippage_bps={float(execution_friction_measurement_payload.get('p95_slippage_bps', 0.0) or 0.0):.4f} "
                    f"| approval_slippage_cap_bps={float(execution_friction_measurement_payload.get('approval_slippage_cap_bps', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- latency_state: {execution_friction_measurement_payload.get('latency_state', 'healthy_latency')} "
                    f"| avg_entry_latency_seconds={float(execution_friction_measurement_payload.get('avg_entry_latency_seconds', 0.0) or 0.0):.2f} "
                    f"| p95_entry_latency_seconds={float(execution_friction_measurement_payload.get('p95_entry_latency_seconds', 0.0) or 0.0):.2f}"
                ),
                (
                    f"- fee_state: {execution_friction_measurement_payload.get('fee_state', 'healthy_fee_drag')} "
                    f"| avg_fee_component_r={float(execution_friction_measurement_payload.get('avg_fee_component_r', 0.0) or 0.0):.4f} "
                    f"| p95_fee_component_r={float(execution_friction_measurement_payload.get('p95_fee_component_r', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- reconciliation_state: {execution_friction_measurement_payload.get('reconciliation_state', 'healthy_reconciliation')} "
                    f"| stress_drag_state={execution_friction_measurement_payload.get('stress_drag_state', 'unknown_stress_drag')}"
                ),
                (
                    f"- fill_rate: {float(execution_friction_measurement_payload.get('fill_rate', 0.0) or 0.0):.4f} "
                    f"| fills_matched={int(execution_friction_measurement_payload.get('fills_matched', 0) or 0)} "
                    f"| execution_fill_coverage={float(execution_friction_measurement_payload.get('execution_fill_coverage', 0.0) or 0.0):.4f}"
                ),
                f"- weakest_axis: {execution_friction_measurement_payload.get('weakest_axis') or 'none'}",
                f"- summary: {execution_friction_measurement_payload.get('summary', '')}",
                f"- reason_codes: {list(execution_friction_measurement_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        forward_stress_regime_validation_payload = dict(forward_stress_regime_validation or {})
        forward_stress_regime_validation_lines: list[str] = []
        if forward_stress_regime_validation_payload:
            source_summary = dict(forward_stress_regime_validation_payload.get("source_summary") or {})
            forward_stress_regime_validation_lines = [
                "## Forward Stress Regime Validation",
                f"- available: {bool(forward_stress_regime_validation_payload.get('available', False))}",
                f"- advisory_only: {bool(forward_stress_regime_validation_payload.get('advisory_only', True))}",
                (
                    f"- validation_state: {forward_stress_regime_validation_payload.get('validation_state', 'insufficient_evidence')} "
                    f"| validation_bias={forward_stress_regime_validation_payload.get('validation_bias', 'gather_more_validation_evidence')}"
                ),
                (
                    f"- coverage_state: {forward_stress_regime_validation_payload.get('coverage_state', 'thin_validation')} "
                    f"| walk_forward_state={forward_stress_regime_validation_payload.get('walk_forward_state', 'insufficient_walk_forward')} "
                    f"| stress_state={forward_stress_regime_validation_payload.get('stress_state', 'insufficient_stress')} "
                    f"| replay_state={forward_stress_regime_validation_payload.get('replay_state', 'replay_lineage_thin')}"
                ),
                (
                    f"- regime_split_state: {forward_stress_regime_validation_payload.get('regime_split_state', 'insufficient_regime_split')} "
                    f"| session_split_state={forward_stress_regime_validation_payload.get('session_split_state', 'insufficient_session_split')}"
                ),
                (
                    f"- preferred_live_mode: {forward_stress_regime_validation_payload.get('preferred_live_mode', 'A_ONLY')} "
                    f"| worst_scenario={forward_stress_regime_validation_payload.get('worst_scenario', 'stressed_cost')} "
                    f"| best_regime={forward_stress_regime_validation_payload.get('best_regime') or 'none'} "
                    f"| best_session={forward_stress_regime_validation_payload.get('best_session') or 'none'}"
                ),
                f"- weakest_axis: {forward_stress_regime_validation_payload.get('weakest_axis') or 'none'}",
                f"- summary: {forward_stress_regime_validation_payload.get('summary', '')}",
                f"- reason_codes: {list(forward_stress_regime_validation_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        kill_condition_automation_payload = dict(kill_condition_automation or {})
        kill_condition_automation_lines: list[str] = []
        if kill_condition_automation_payload:
            source_summary = dict(kill_condition_automation_payload.get("source_summary") or {})
            kill_condition_automation_lines = [
                "## Kill Condition Automation",
                f"- available: {bool(kill_condition_automation_payload.get('available', False))}",
                f"- advisory_only: {bool(kill_condition_automation_payload.get('advisory_only', True))}",
                (
                    f"- kill_condition_state: {kill_condition_automation_payload.get('kill_condition_state', 'observe_only')} "
                    f"| automation_bias={kill_condition_automation_payload.get('automation_bias', 'observe_only')} "
                    f"| write_scope={kill_condition_automation_payload.get('write_scope', 'none')}"
                ),
                (
                    f"- trigger_axis: {kill_condition_automation_payload.get('trigger_axis', 'none')} "
                    f"| active_manual_override={bool(kill_condition_automation_payload.get('active_manual_override', False))} "
                    f"| arm_required={bool(kill_condition_automation_payload.get('arm_required', False))}"
                ),
                (
                    f"- manual_override_reason: {kill_condition_automation_payload.get('manual_override_reason') or 'none'} "
                    f"| trigger_reason_codes={list(kill_condition_automation_payload.get('trigger_reason_codes') or [])}"
                ),
                f"- summary: {kill_condition_automation_payload.get('summary', '')}",
                f"- reason_codes: {list(kill_condition_automation_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        v2_payload = dict(strategy_v2_validation or {})
        v2_metrics = dict(v2_payload.get("mode_metrics") or {})
        a_only = dict(v2_metrics.get("A_ONLY") or {})
        a_plus_b = dict(v2_metrics.get("A_PLUS_B") or {})
        family_summary = dict(v2_payload.get("family_summary") or {})
        regime_summary = dict(v2_payload.get("regime_summary") or {})
        session_summary = dict(v2_payload.get("session_summary") or {})
        v2_comparison = dict(v2_payload.get("comparison") or {})
        v2_recommendation = dict(v2_payload.get("deployment_recommendation") or {})
        v2_lines: list[str] = []
        if v2_payload:
            v2_lines = [
                "## Strategy v2 Mode Comparison",
                f"- available: {bool(v2_payload.get('available', False))}",
                f"- comparison_axis: {v2_payload.get('comparison_axis', 'strategy_mode')}",
                f"- eligible_closed_trades: {int((v2_payload.get('sample_counts') or {}).get('eligible_closed_trades', 0))}",
                f"- incremental_b_trades: {int((v2_payload.get('sample_counts') or {}).get('incremental_b_trades', 0))}",
                f"- preferred_live_mode: {v2_recommendation.get('preferred_live_mode', 'A_ONLY')}",
                f"- recommendation_reason: {v2_recommendation.get('reason', 'not_available')}",
                f"- best_ev_family: {dict(family_summary.get('best_ev_family') or {}).get('name')}",
                f"- best_ev_regime: {dict(regime_summary.get('best_ev_regime') or {}).get('name')}",
                f"- best_ev_session: {dict(session_summary.get('best_ev_session') or {}).get('name')}",
                (
                    f"- A_ONLY: trades={int(a_only.get('trades', 0))}, ev={float(a_only.get('ev', 0.0)):.4f}, "
                    f"p5={float(a_only.get('p5_ev', 0.0)):.4f}, max_dd={float(a_only.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(a_only.get('ulcer_index', 0.0)):.4f}, forced_exit_ratio={float(a_only.get('forced_exit_ratio', 0.0)):.4f}, "
                    f"information_failure_ratio={float(a_only.get('information_failure_ratio', 0.0)):.4f}"
                ),
                (
                    f"- A_PLUS_B: trades={int(a_plus_b.get('trades', 0))}, ev={float(a_plus_b.get('ev', 0.0)):.4f}, "
                    f"p5={float(a_plus_b.get('p5_ev', 0.0)):.4f}, max_dd={float(a_plus_b.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(a_plus_b.get('ulcer_index', 0.0)):.4f}, forced_exit_ratio={float(a_plus_b.get('forced_exit_ratio', 0.0)):.4f}, "
                    f"information_failure_ratio={float(a_plus_b.get('information_failure_ratio', 0.0)):.4f}"
                ),
                (
                    f"- delta(A_PLUS_B - A_ONLY): ev={float(v2_comparison.get('ev', 0.0)):.4f}, "
                    f"p5={float(v2_comparison.get('p5_ev', 0.0)):.4f}, max_dd={float(v2_comparison.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(v2_comparison.get('ulcer_index', 0.0)):.4f}"
                ),
                "",
            ]

        multi_strategy_ab_payload = dict(multi_strategy_ab or {})
        multi_strategy_ab_lines: list[str] = []
        if multi_strategy_ab_payload:
            multi_strategy_ab_lines = [
                "## Multi Strategy AB Expansion",
                f"- available: {bool(multi_strategy_ab_payload.get('available', False))}",
                f"- advisory_only: {bool(multi_strategy_ab_payload.get('advisory_only', True))}",
                f"- mode: {multi_strategy_ab_payload.get('mode', 'A_ONLY')}",
                f"- raw_family_anchor: {multi_strategy_ab_payload.get('raw_family_anchor', 'sweep_reversal')}",
                f"- summary: {multi_strategy_ab_payload.get('summary', '')}",
                f"- reason_codes: {list(multi_strategy_ab_payload.get('reason_codes') or [])}",
                f"- a_cluster: {dict(multi_strategy_ab_payload.get('a_cluster') or {})}",
                f"- b_cluster: {dict(multi_strategy_ab_payload.get('b_cluster') or {})}",
                f"- research_sidecar: {dict(multi_strategy_ab_payload.get('research_sidecar') or {})}",
                f"- family_mix: {list(multi_strategy_ab_payload.get('family_mix') or [])}",
                "",
            ]

        b_continuation_activation_payload = dict(b_continuation_activation or {})
        b_continuation_activation_lines: list[str] = []
        if b_continuation_activation_payload:
            source_summary = dict(b_continuation_activation_payload.get("source_summary") or {})
            b_continuation_activation_lines = [
                "## B Continuation Activation",
                f"- available: {bool(b_continuation_activation_payload.get('available', False))}",
                f"- advisory_only: {bool(b_continuation_activation_payload.get('advisory_only', True))}",
                f"- family: {b_continuation_activation_payload.get('family', 'trend_continuation')}",
                (
                    f"- activation_state: {b_continuation_activation_payload.get('activation_state', 'research_only')} "
                    f"| activation_bias={b_continuation_activation_payload.get('activation_bias', 'stay_research')} "
                    f"| target_mode={b_continuation_activation_payload.get('target_mode', 'A_ONLY')} "
                    f"| confidence={b_continuation_activation_payload.get('confidence', 'low')}"
                ),
                (
                    f"- live_eligible: {bool(b_continuation_activation_payload.get('live_eligible', False))} "
                    f"| summary: {b_continuation_activation_payload.get('summary', '')}"
                ),
                f"- reason_codes: {list(b_continuation_activation_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        b_continuation_edge_validation_payload = dict(b_continuation_edge_validation or {})
        b_continuation_edge_validation_lines: list[str] = []
        if b_continuation_edge_validation_payload:
            source_summary = dict(b_continuation_edge_validation_payload.get("source_summary") or {})
            b_continuation_edge_validation_lines = [
                "## B Continuation Edge Validation",
                f"- available: {bool(b_continuation_edge_validation_payload.get('available', False))}",
                f"- advisory_only: {bool(b_continuation_edge_validation_payload.get('advisory_only', True))}",
                (
                    f"- raw_family: {b_continuation_edge_validation_payload.get('raw_family', 'trend_continuation')} "
                    f"| strategy_cluster={b_continuation_edge_validation_payload.get('strategy_cluster', 'b_continuation')}"
                ),
                (
                    f"- edge_state: {b_continuation_edge_validation_payload.get('edge_state', 'insufficient_sample')} "
                    f"| validation_bias={b_continuation_edge_validation_payload.get('validation_bias', 'gather_more_evidence')} "
                    f"| sample_state={b_continuation_edge_validation_payload.get('sample_state', 'thin_sample')} "
                    f"| confidence={b_continuation_edge_validation_payload.get('confidence', 'low')}"
                ),
                (
                    f"- family_post_cost_rate: {float(b_continuation_edge_validation_payload.get('family_post_cost_rate', 0.0) or 0.0):.4f} "
                    f"| family_post_cost_ev={b_continuation_edge_validation_payload.get('family_post_cost_ev')}"
                ),
                (
                    f"- diversification_state: {b_continuation_edge_validation_payload.get('diversification_state', 'unclear_diversification')} "
                    f"| drawdown_contribution_state={b_continuation_edge_validation_payload.get('drawdown_contribution_state', 'drawdown_unknown')} "
                    f"| a_b_correlation_proxy={b_continuation_edge_validation_payload.get('a_b_correlation_proxy', 'unknown_proxy')}"
                ),
                (
                    f"- weakest_axis: {b_continuation_edge_validation_payload.get('weakest_axis') or 'none'} "
                    f"| weakest_bucket={b_continuation_edge_validation_payload.get('weakest_bucket') or 'none'}"
                ),
                f"- summary: {b_continuation_edge_validation_payload.get('summary', '')}",
                f"- reason_codes: {list(b_continuation_edge_validation_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        strategy_cluster_balance_payload = dict(strategy_cluster_balance or {})
        strategy_cluster_balance_lines: list[str] = []
        if strategy_cluster_balance_payload:
            source_summary = dict(strategy_cluster_balance_payload.get("source_summary") or {})
            strategy_cluster_balance_lines = [
                "## Strategy Cluster Balance",
                f"- available: {bool(strategy_cluster_balance_payload.get('available', False))}",
                f"- advisory_only: {bool(strategy_cluster_balance_payload.get('advisory_only', True))}",
                f"- mode: {strategy_cluster_balance_payload.get('mode', 'A_ONLY')}",
                (
                    f"- balance_state: {strategy_cluster_balance_payload.get('balance_state', 'a_concentrated')} "
                    f"| balance_bias={strategy_cluster_balance_payload.get('balance_bias', 'preserve_a_anchor')} "
                    f"| headline_cluster={strategy_cluster_balance_payload.get('headline_cluster', 'a_reversal')} "
                    f"| target_mix={strategy_cluster_balance_payload.get('target_mix', 'a_anchor_only')} "
                    f"| confidence={strategy_cluster_balance_payload.get('confidence', 'low')}"
                ),
                f"- summary: {strategy_cluster_balance_payload.get('summary', '')}",
                f"- family_mix: {list(strategy_cluster_balance_payload.get('family_mix') or [])}",
                f"- reason_codes: {list(strategy_cluster_balance_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        a_strategy_post_cost_edge_validation_payload = dict(a_strategy_post_cost_edge_validation or {})
        a_strategy_post_cost_edge_validation_lines: list[str] = []
        if a_strategy_post_cost_edge_validation_payload:
            source_summary = dict(a_strategy_post_cost_edge_validation_payload.get("source_summary") or {})
            a_strategy_post_cost_edge_validation_lines = [
                "## A Strategy Post-Cost Edge Validation",
                f"- available: {bool(a_strategy_post_cost_edge_validation_payload.get('available', False))}",
                f"- advisory_only: {bool(a_strategy_post_cost_edge_validation_payload.get('advisory_only', True))}",
                f"- family: {a_strategy_post_cost_edge_validation_payload.get('family', 'sweep_reversal')}",
                (
                    f"- edge_state: {a_strategy_post_cost_edge_validation_payload.get('edge_state', 'insufficient_sample')} "
                    f"| validation_bias={a_strategy_post_cost_edge_validation_payload.get('validation_bias', 'gather_more_evidence')} "
                    f"| sample_state={a_strategy_post_cost_edge_validation_payload.get('sample_state', 'thin')} "
                    f"| confidence={a_strategy_post_cost_edge_validation_payload.get('confidence', 'low')}"
                ),
                (
                    f"- family_post_cost_rate: {float(a_strategy_post_cost_edge_validation_payload.get('family_post_cost_rate', 0.0) or 0.0):.4f} "
                    f"| family_post_cost_ev={a_strategy_post_cost_edge_validation_payload.get('family_post_cost_ev')}"
                ),
                (
                    f"- weakest_axis: {a_strategy_post_cost_edge_validation_payload.get('weakest_axis') or 'none'} "
                    f"| weakest_bucket={a_strategy_post_cost_edge_validation_payload.get('weakest_bucket') or 'none'}"
                ),
                f"- summary: {a_strategy_post_cost_edge_validation_payload.get('summary', '')}",
                f"- reason_codes: {list(a_strategy_post_cost_edge_validation_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        scalp_payload = dict(strategy_v2_scalp_experiment or {})
        scalp_comparison = dict(scalp_payload.get("comparison") or {})
        scalp_lines: list[str] = []
        if scalp_payload:
            scalp_lines = [
                "## Scalp Experiment (5m zone / 1m execution)",
                f"- available: {bool(scalp_payload.get('available', False))}",
                f"- reason: {scalp_payload.get('reason', 'not_available')}",
                f"- preferred_branch: {scalp_comparison.get('preferred_branch', 'none')}",
                f"- recommendation_reason: {scalp_comparison.get('recommendation_reason', 'not_available')}",
                f"- delta_top_expected_ev_at_size_r: {float(scalp_comparison.get('delta_top_expected_ev_at_size_r', 0.0)):+.4f}",
                f"- delta_top_expected_win_prob: {float(scalp_comparison.get('delta_top_expected_win_prob', 0.0)):+.4f}",
                (
                    f"- sample_counts: candles_1m={int((scalp_payload.get('sample_counts') or {}).get('candles_1m', 0))}, "
                    f"candles_5m={int((scalp_payload.get('sample_counts') or {}).get('candles_5m', 0))}, "
                    f"candles_15m={int((scalp_payload.get('sample_counts') or {}).get('candles_15m', 0))}"
                ),
                "",
            ]

        edge_experiment_preview_summary = summarize_edge_experiment_review(
            build_edge_experiment_review(score_to_outcome_funnel=dict(score_to_outcome_funnel or {}))
        )
        edge_operating_discipline_preview = dict((edge_experiment_preview_summary or {}).get("operating_discipline") or {})
        alpha_research_payload = dict(alpha_research_pipeline or {})
        alpha_research_summary = dict(alpha_research_payload.get("summary") or {})
        alpha_research_alignment = dict(alpha_research_payload.get("research_focus_alignment") or {})
        alpha_research_action_summary = dict(alpha_research_payload.get("recommended_action_summary") or {})
        alpha_research_actions = list(alpha_research_payload.get("recommended_actions") or [])
        alpha_research_top_experiment = dict(alpha_research_payload.get("top_shadow_experiment") or {})
        alpha_research_experiment_templates = list(alpha_research_payload.get("shadow_experiment_templates") or [])
        alpha_research_evidence_summary = dict(alpha_research_payload.get("alpha_research_evidence_summary") or {})
        alpha_research_reason_summary = dict(alpha_research_evidence_summary.get("near_miss_reason_summary") or {})
        alpha_research_focus_summary = dict(alpha_research_evidence_summary.get("focus_alignment_summary") or {})
        alpha_research_outcome_summary = dict(alpha_research_evidence_summary.get("outcome_alignment_summary") or {})
        alpha_research_softening_review = dict(alpha_research_payload.get("softening_candidate_review") or {})
        alpha_research_promotion_watchlist = dict(alpha_research_payload.get("promotion_watchlist") or {})
        alpha_research_experiment_sequence = dict(alpha_research_payload.get("experiment_sequence") or {})
        alpha_research_lines: list[str] = []
        if alpha_research_payload:
            alpha_research_lines = [
                "## Alpha Research Pipeline",
                f"- available: {bool(alpha_research_payload.get('available', False))}",
                f"- reason: {alpha_research_payload.get('reason', 'not_available')}",
                f"- analysis_symbol: {alpha_research_payload.get('analysis_symbol')}",
                f"- alpha_research_candidate_count: {int(alpha_research_summary.get('alpha_research_candidate_count', 0))}",
                f"- focus_symbol_candidate_count: {int(alpha_research_summary.get('focus_symbol_candidate_count', 0))}",
                f"- top_reason: {alpha_research_summary.get('top_reason')}",
                f"- top_family: {alpha_research_summary.get('top_family')}",
                f"- top_regime: {alpha_research_summary.get('top_regime')}",
                f"- top_session: {alpha_research_summary.get('top_session')}",
                f"- avg_softened_risk_r: {float(alpha_research_summary.get('avg_softened_risk_r', 0.0)):.4f}",
                f"- aligned_candidate_count: {int(alpha_research_alignment.get('aligned_candidate_count', 0))}",
                f"- top_alignment_focus: {alpha_research_alignment.get('top_focus')}",
                f"- top_alignment_bucket: {alpha_research_alignment.get('top_bucket')}",
                f"- recommended_action: {alpha_research_action_summary.get('recommended_action')}",
                f"- recommended_scope: {alpha_research_action_summary.get('recommended_scope')}",
                f"- recommended_reason: {alpha_research_action_summary.get('recommended_reason')}",
                f"- shadow_experiment_type: {alpha_research_action_summary.get('shadow_experiment_type')}",
                f"- recommended_focus: {alpha_research_action_summary.get('focus')}",
                f"- recommended_bucket: {alpha_research_action_summary.get('bucket')}",
                f"- confidence: {alpha_research_action_summary.get('confidence')}",
                f"- sample_note: {alpha_research_action_summary.get('sample_note')}",
                f"- recommended_action_deferred_by_sequence: {bool(alpha_research_action_summary.get('deferred_by_experiment_sequence', False))}",
                f"- recommended_action_current_priority: {alpha_research_action_summary.get('current_priority_experiment')}:{alpha_research_action_summary.get('current_priority_action')}",
                f"- top_shadow_experiment_id: {alpha_research_top_experiment.get('experiment_id')}",
                f"- top_shadow_experiment_title: {alpha_research_top_experiment.get('title')}",
                f"- top_shadow_experiment_target: {alpha_research_top_experiment.get('target')}",
                f"- top_shadow_experiment_confidence: {alpha_research_top_experiment.get('confidence')}",
                f"- top_shadow_experiment_objective: {alpha_research_top_experiment.get('objective')}",
                f"- top_shadow_experiment_deferred_by_sequence: {bool(alpha_research_top_experiment.get('deferred_by_experiment_sequence', False))}",
                (
                    f"- experiment_sequence: state={alpha_research_experiment_sequence.get('state')} | "
                    f"entry_timing_locked={bool(alpha_research_experiment_sequence.get('entry_timing_locked', False))} | "
                    f"execution_style_locked={bool(alpha_research_experiment_sequence.get('execution_style_locked', False))} | "
                    f"exit_optimization_allowed={bool(alpha_research_experiment_sequence.get('exit_optimization_allowed', False))} | "
                    f"current_priority={alpha_research_experiment_sequence.get('current_priority_experiment')}:{alpha_research_experiment_sequence.get('current_priority_action')}"
                ),
                f"- experiment_sequence_summary: {alpha_research_experiment_sequence.get('summary')}",
                f"- evidence_available: {bool(alpha_research_evidence_summary.get('available', False))}",
                f"- evidence_top_reason: {alpha_research_reason_summary.get('top_reason')}",
                f"- evidence_focus_aligned_candidates: {int(alpha_research_focus_summary.get('aligned_candidate_count', 0) or 0)}",
                f"- evidence_top_focus: {alpha_research_focus_summary.get('top_focus')}:{alpha_research_focus_summary.get('top_bucket')}",
                f"- evidence_top_family_bottleneck: {dict(alpha_research_outcome_summary.get('top_family_bottleneck') or {}).get('key')}",
                f"- evidence_top_regime_bottleneck: {dict(alpha_research_outcome_summary.get('top_regime_bottleneck') or {}).get('key')}",
                f"- evidence_top_session_bottleneck: {dict(alpha_research_outcome_summary.get('top_session_bottleneck') or {}).get('key')}",
                f"- softening_review_available: {bool(alpha_research_softening_review.get('available', False))}",
                f"- softening_top_bucket: {dict(alpha_research_softening_review.get('top_candidate') or {}).get('bucket')}",
                f"- softening_top_priority: {dict(alpha_research_softening_review.get('top_candidate') or {}).get('review_priority')}",
                f"- promotion_watchlist_available: {bool(alpha_research_promotion_watchlist.get('available', False))}",
                f"- promotion_watchlist_count: {int(alpha_research_promotion_watchlist.get('watchlist_count', 0) or 0)}",
                f"- improvement_priority: {edge_operating_discipline_preview.get('improvement_priority')}",
                f"- signal_density_control_review_allowed: {bool(edge_operating_discipline_preview.get('signal_density_control_review_allowed', False))}",
                f"- multi_strategy_expansion_review_allowed: {bool(edge_operating_discipline_preview.get('multi_strategy_expansion_review_allowed', False))}",
                "",
            ]
            for idx, row in enumerate(alpha_research_actions[:3], start=1):
                alpha_research_lines.append(
                    f"- action_{idx}: {row.get('recommended_action')} [{row.get('recommended_scope')}] "
                    f"bucket={row.get('bucket')} reason={row.get('recommended_reason')} "
                    f"confidence={row.get('confidence')} observe={row.get('observe_metrics', [])}"
                )
            for idx, row in enumerate(alpha_research_experiment_templates[:3], start=1):
                alpha_research_lines.append(
                    f"- experiment_{idx}: {row.get('experiment_id')} title={row.get('title')} "
                    f"target={row.get('target')} confidence={row.get('confidence')} "
                    f"observe={row.get('observe_metrics', [])}"
                )
            for idx, row in enumerate(list(alpha_research_evidence_summary.get("false_negative_suspects") or [])[:3], start=1):
                alpha_research_lines.append(
                    f"- suspect_{idx}: {row.get('axis')}:{row.get('bucket')} "
                    f"reason={row.get('reason')} alignment={row.get('alignment_strength')} "
                    f"execution_drag_conflict={bool(row.get('execution_drag_conflict', False))}"
                )
            for idx, row in enumerate(list(alpha_research_softening_review.get("review_items") or [])[:3], start=1):
                alpha_research_lines.append(
                    f"- softening_{idx}: {row.get('review_priority')} {row.get('axis')}:{row.get('bucket')} "
                    f"reason={row.get('reason')} action={row.get('recommended_research_action')} "
                    f"conflict={bool(row.get('execution_drag_conflict', False))}"
                )
            for idx, row in enumerate(list(alpha_research_promotion_watchlist.get("watch_items") or [])[:3], start=1):
                alpha_research_lines.append(
                    f"- watch_{idx}: bucket={row.get('bucket')} focus={row.get('focus')} "
                    f"template={row.get('recent_shadow_template')} not_ready={row.get('not_ready_reason')}"
                )
            alpha_research_lines.append("")

        score_to_outcome_payload = dict(score_to_outcome_funnel or {})
        score_to_outcome_snapshot = dict(score_to_outcome_payload.get("snapshot_selection") or {})
        score_to_outcome_history = dict(score_to_outcome_payload.get("historical_execution_outcomes") or {})
        score_to_outcome_decomposition = dict(score_to_outcome_payload.get("decomposition") or {})
        money_funnel_payload = dict(score_to_outcome_payload.get("money_funnel") or {})
        outcome_operating_kpis = dict(build_outcome_funnel_operating_kpis(score_to_outcome_payload) or {})
        score_to_outcome_lines: list[str] = []
        if score_to_outcome_payload:
            score_to_outcome_lines = [
                "## Score To Outcome Funnel",
                f"- available: {bool(score_to_outcome_payload.get('available', False))}",
                f"- reason: {score_to_outcome_payload.get('reason', 'not_available')}",
                f"- report_window_days: {int(score_to_outcome_payload.get('report_window_days', 0) or 0)}",
                f"- coverage_note: {score_to_outcome_payload.get('coverage_note', '')}",
                (
                    f"- snapshot_selection: runtime={int(score_to_outcome_snapshot.get('runtime_candidates', 0) or 0)}, "
                    f"accepted={int(score_to_outcome_snapshot.get('accepted_candidates', 0) or 0)}, "
                    f"blocked={int(score_to_outcome_snapshot.get('blocked_candidates', 0) or 0)}, "
                    f"accept_rate={float(score_to_outcome_snapshot.get('accept_rate', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- historical_execution_outcomes: submitted={int(score_to_outcome_history.get('submitted', 0) or 0)}, "
                    f"filled={int(score_to_outcome_history.get('filled', 0) or 0)}, "
                    f"closed={int(score_to_outcome_history.get('closed', 0) or 0)}, "
                    f"profitable={int(score_to_outcome_history.get('profitable', 0) or 0)}, "
                    f"baseline_cost_profitable={int(score_to_outcome_history.get('baseline_cost_profitable', 0) or 0)}"
                ),
                (
                    f"- historical_rates: fill_from_submitted={float(score_to_outcome_history.get('fill_rate_from_submitted', 0.0) or 0.0):.4f}, "
                    f"close_from_filled={float(score_to_outcome_history.get('close_rate_from_filled', 0.0) or 0.0):.4f}, "
                    f"profitable_from_closed={float(score_to_outcome_history.get('profitable_rate_from_closed', 0.0) or 0.0):.4f}, "
                    f"baseline_cost_profitable_from_closed={float(score_to_outcome_history.get('baseline_cost_profitable_rate_from_closed', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- operating_kpis: primary_focus={outcome_operating_kpis.get('primary_focus', 'after_cost_edge_proof')} | "
                    f"runtime_accept={float(dict(outcome_operating_kpis.get('stage_conversion_rates') or {}).get('runtime_to_accepted', 0.0) or 0.0):.4f} | "
                    f"submitted_fill={float(dict(outcome_operating_kpis.get('stage_conversion_rates') or {}).get('submitted_to_filled', 0.0) or 0.0):.4f} | "
                    f"filled_close={float(dict(outcome_operating_kpis.get('stage_conversion_rates') or {}).get('filled_to_closed', 0.0) or 0.0):.4f} | "
                    f"closed_post_cost_survival={float(outcome_operating_kpis.get('cost_adjusted_survival_rate', 0.0) or 0.0):.4f} | "
                    f"closed_per_day={float(outcome_operating_kpis.get('closed_trades_per_day', 0.0) or 0.0):.4f}"
                ),
                f"- operating_kpi_summary: {outcome_operating_kpis.get('summary', '')}",
            ]
            for axis in ("family", "regime", "session"):
                row = dict((list(score_to_outcome_decomposition.get(axis) or [])[:1] or [{}])[0])
                if row:
                    score_to_outcome_lines.append(
                        f"- top_{axis}_bucket: key={row.get('key')} runtime={int(row.get('runtime_candidates', 0) or 0)} "
                        f"submitted={int(row.get('submitted', 0) or 0)} filled={int(row.get('filled', 0) or 0)} "
                        f"closed={int(row.get('closed', 0) or 0)} profitable_rate={float(row.get('profitable_rate_from_closed', 0.0) or 0.0):.4f} "
                        f"baseline_cost_profitable_rate={float(row.get('baseline_cost_profitable_rate_from_closed', 0.0) or 0.0):.4f}"
                    )
            score_to_outcome_lines.append("")
        money_funnel_lines: list[str] = []
        if money_funnel_payload:
            snapshot_expected = dict(money_funnel_payload.get("snapshot_expected_r") or {})
            historical_expected = dict(money_funnel_payload.get("historical_expected_r") or {})
            historical_realized = dict(money_funnel_payload.get("historical_realized_r") or {})
            historical_gap = dict(money_funnel_payload.get("historical_gap_r") or {})
            money_funnel_lines = [
                "## Money Funnel",
                f"- available: {bool(money_funnel_payload.get('available', False))}",
                f"- coverage_note: {money_funnel_payload.get('coverage_note', '')}",
                (
                    f"- snapshot_expected_r: runtime={float(snapshot_expected.get('runtime_candidates', 0.0) or 0.0):.4f}, "
                    f"accepted={float(snapshot_expected.get('accepted_candidates', 0.0) or 0.0):.4f}, "
                    f"blocked={float(snapshot_expected.get('blocked_candidates', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- historical_expected_r: generated={float(historical_expected.get('generated', 0.0) or 0.0):.4f}, "
                    f"submitted={float(historical_expected.get('submitted', 0.0) or 0.0):.4f}, "
                    f"filled={float(historical_expected.get('filled', 0.0) or 0.0):.4f}, "
                    f"closed={float(historical_expected.get('closed', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- historical_realized_r: raw_closed={float(historical_realized.get('raw_closed', 0.0) or 0.0):.4f}, "
                    f"post_cost_closed={float(historical_realized.get('post_cost_closed', 0.0) or 0.0):.4f}, "
                    f"cost_drag={float(historical_realized.get('cost_drag', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- historical_gap_r: generated_to_submitted={float(historical_gap.get('generated_to_submitted', 0.0) or 0.0):.4f}, "
                    f"submitted_to_filled={float(historical_gap.get('submitted_to_filled', 0.0) or 0.0):.4f}, "
                    f"filled_to_closed={float(historical_gap.get('filled_to_closed', 0.0) or 0.0):.4f}, "
                    f"closed_expected_to_post_cost_realized={float(historical_gap.get('closed_expected_to_post_cost_realized', 0.0) or 0.0):.4f}"
                ),
                f"- summary: {money_funnel_payload.get('summary', '')}",
                "",
            ]

        execution_degradation_payload = dict(execution_degradation_advisory or {})
        execution_degradation_reasons = list(execution_degradation_payload.get("reasons") or [])
        execution_degradation_lines: list[str] = []
        if execution_degradation_payload:
            execution_degradation_lines = [
                "## Execution Degradation Advisory",
                f"- available: {bool(execution_degradation_payload.get('available', False))}",
                f"- status: {execution_degradation_payload.get('status', 'healthy')}",
                f"- healthy: {bool(execution_degradation_payload.get('healthy', True))}",
                f"- summary: {execution_degradation_payload.get('summary', '')}",
                f"- recommended_action: {execution_degradation_payload.get('recommended_action', 'continue_runtime_monitoring')}",
                f"- reason_codes: {list(execution_degradation_payload.get('reason_codes') or [])}",
                f"- sample_context: {dict(execution_degradation_payload.get('sample_context') or {})}",
                "",
            ]
            for idx, reason in enumerate(execution_degradation_reasons[:5], start=1):
                execution_degradation_lines.append(
                    f"- reason_{idx}: {reason.get('code')} [{reason.get('severity')}] "
                    f"{reason.get('message')} action={reason.get('recommended_action')} evidence={reason.get('evidence', {})}"
                )
            execution_degradation_lines.append("")

        family_execution_degradation_payload = dict(family_execution_degradation_advisory or {})
        family_execution_degradation_rows = list(family_execution_degradation_payload.get("families") or [])
        family_execution_degradation_lines: list[str] = []
        if family_execution_degradation_payload:
            family_execution_degradation_lines = [
                "## Family Execution Degradation Advisory",
                f"- available: {bool(family_execution_degradation_payload.get('available', False))}",
                f"- coverage_note: {family_execution_degradation_payload.get('coverage_note', '')}",
            ]
            for idx, row in enumerate(family_execution_degradation_rows[:3], start=1):
                family_execution_degradation_lines.append(
                    f"- family_{idx}: {row.get('family')} status={row.get('status')} "
                    f"confidence={row.get('confidence')} post_cost_alignment={row.get('post_cost_alignment')} "
                    f"reasons={list(row.get('reason_codes') or [])}"
                )
            family_execution_degradation_lines.append("")

        mode_advisory_payload = dict(mode_advisory or {})
        mode_advisory_lines: list[str] = []
        if mode_advisory_payload:
            mode_advisory_lines = [
                "## Mode Advisory",
                f"- available: {bool(mode_advisory_payload.get('available', False))}",
                f"- coverage_note: {mode_advisory_payload.get('coverage_note', '')}",
            ]
            for axis in ("family", "regime", "session"):
                top_row = dict((list(mode_advisory_payload.get(axis) or [])[:1] or [{}])[0])
                mode_advisory_lines.append(
                    f"- top_{axis}: bucket={top_row.get('bucket')} state={top_row.get('advisory_state')} "
                    f"confidence={top_row.get('confidence')} why={top_row.get('why')}"
                )
            mode_advisory_lines.append("")

        operator_action_priority_payload = self._normalize_operator_action_priority_payload(
            operator_action_priority,
            symbol=symbol,
            universe=str(getattr(self.settings, "universe_name", "usdc_perp_top30") or "usdc_perp_top30"),
            days=max(int(score_to_outcome_payload.get("report_window_days", 0) or 0), 1) if score_to_outcome_payload else 7,
        )
        operator_action_priority_lines: list[str] = []
        if operator_action_priority_payload:
            operator_action_priority_lines = [
                "## Operator Action Priority",
                f"- available: {bool(operator_action_priority_payload.get('available', False))}",
                f"- top_action: {operator_action_priority_payload.get('top_action', 'continue_runtime_monitoring')}",
                f"- top_reason: {operator_action_priority_payload.get('top_reason', '')}",
                f"- top_action_followup_command: {operator_action_priority_payload.get('top_action_followup_command', '')}",
                f"- priority_level: {operator_action_priority_payload.get('priority_level', 'monitor')}",
                f"- priority_source: {operator_action_priority_payload.get('priority_source', 'monitor')}",
                f"- action_family: {operator_action_priority_payload.get('action_family', 'monitor')}",
                f"- advisory_only: {bool(operator_action_priority_payload.get('advisory_only', True))}",
            ]
            experiment_policy = dict(operator_action_priority_payload.get("experiment_execution_policy") or {})
            if experiment_policy:
                operator_action_priority_lines.append(
                    f"- experiment_policy: mode={experiment_policy.get('mode', 'single_active_experiment')} "
                    f"active_action={experiment_policy.get('active_action', 'none')} "
                    f"sample_maturity={experiment_policy.get('sample_maturity_state', 'unknown')} "
                    f"next_target_closed_trades={int(experiment_policy.get('next_sample_target_closed_trades', 0) or 0)}"
                )
            capture_context = dict(operator_action_priority_payload.get("capture_context") or {})
            if capture_context:
                dominant_bottleneck = dict(capture_context.get("dominant_bottleneck") or {})
                family_focus = dict(capture_context.get("family_focus") or {})
                operator_action_priority_lines.extend(
                    [
                        f"- capture_context.dominant_bottleneck: stage={dominant_bottleneck.get('stage')} reason={dominant_bottleneck.get('reason')}",
                        f"- capture_context.family_focus: {family_focus.get('key')}",
                        f"- capture_context.maturity: {capture_context.get('maturity', 'unknown')}",
                    ]
                )
            experiment_context = dict(operator_action_priority_payload.get("experiment_context") or {})
            if experiment_context:
                operator_action_priority_lines.extend(
                    [
                        (
                            f"- experiment_context: edge_state={experiment_context.get('edge_state')} "
                            f"true_edge_ratio={float(experiment_context.get('true_edge_ratio', 0.0) or 0.0):.4f} "
                            f"edge_decay_rate={float(experiment_context.get('edge_decay_rate', 0.0) or 0.0):+.4f}"
                        ),
                        (
                            f"- experiment_context.sample: state={experiment_context.get('sample_maturity_state', 'unknown')} "
                            f"remaining_to_next_target={int(experiment_context.get('remaining_closed_trades_to_next_target', 0) or 0)} "
                            f"regime_dependency={experiment_context.get('regime_dependency_state', 'not_available')}"
                        ),
                        (
                            f"- experiment_context.entry_timing: preferred={experiment_context.get('entry_timing_preferred_variant')} "
                            f"ready={bool(experiment_context.get('entry_timing_comparison_ready', False))} "
                            f"reason={experiment_context.get('entry_timing_recommendation_reason')}"
                        ),
                        (
                            f"- experiment_context.execution_style: preferred={experiment_context.get('execution_style_preferred_variant')} "
                            f"ready={bool(experiment_context.get('execution_style_comparison_ready', False))} "
                            f"reason={experiment_context.get('execution_style_recommendation_reason')}"
                        ),
                    ]
                )
                for label, key in (
                    ("accepted_candidate_focus", "accepted_candidate_focus"),
                    ("blocked_candidate_focus", "blocked_candidate_focus"),
                    ("entry_timing_target", "entry_timing_target"),
                    ("execution_style_target", "execution_style_target"),
                ):
                    target = dict(experiment_context.get(key) or {})
                    if not target:
                        continue
                    operator_action_priority_lines.append(
                        f"- experiment_context.{label}: symbol={target.get('symbol')} status={target.get('status')} "
                        f"family={target.get('strategy_family')} edge_state={target.get('edge_state')} "
                        f"entry={target.get('entry_timing_preferred_variant')} "
                        f"execution={target.get('execution_style_preferred_variant')} "
                        f"block_reason={target.get('block_reason')} focus={target.get('focus_source')} "
                        f"cmd={target.get('followup_command')}"
                    )
            for idx, row in enumerate(list(operator_action_priority_payload.get("deferred_experiment_actions") or [])[:2], start=1):
                operator_action_priority_lines.append(
                    f"- deferred_experiment_{idx}: action={row.get('action')} "
                    f"reason={row.get('defer_reason')} target={row.get('target_symbol') or 'none'}"
                )
            for idx, row in enumerate(list(operator_action_priority_payload.get("next_actions") or [])[:3], start=1):
                target_suffix = ""
                if row.get("target_symbol"):
                    target_suffix = (
                        f" target={row.get('target_symbol')}:{row.get('target_status')}:{row.get('target_family')} "
                        f"block={row.get('target_block_reason')} focus={row.get('target_focus_source')}"
                    )
                command_suffix = f" cmd={row.get('followup_command')}" if row.get("followup_command") else ""
                operator_action_priority_lines.append(
                    f"- next_{idx}: action={row.get('action')} priority={row.get('priority_level')} "
                    f"source={row.get('source')} family={row.get('action_family')} reason={row.get('reason')}{target_suffix}{command_suffix}"
                )
            operator_action_priority_lines.append("")

        outcome_control_trace = build_outcome_control_trace(
            execution_degradation_advisory=execution_degradation_payload,
            family_execution_degradation_advisory=family_execution_degradation_payload,
            mode_advisory=mode_advisory_payload,
            score_to_outcome_funnel=score_to_outcome_payload,
        )
        outcome_control_trace_summary = summarize_outcome_control_trace(outcome_control_trace)
        outcome_control_trace_lines: list[str] = []
        if outcome_control_trace_summary:
            outcome_control_trace_lines = [
                "## Outcome Control Trace",
                f"- available: {bool(outcome_control_trace_summary.get('available', False))}",
                f"- summary: {outcome_control_trace_summary.get('summary', '')}",
                (
                    f"- approval_penalty: status={outcome_control_trace_summary.get('approval_penalty_status', 'healthy')} "
                    f"tier={outcome_control_trace_summary.get('approval_penalty_tier', 'none')}"
                ),
                (
                    f"- sizing_penalty: status={outcome_control_trace_summary.get('sizing_penalty_status', 'healthy')} "
                    f"tier={outcome_control_trace_summary.get('sizing_penalty_tier', 'none')} "
                    f"multiplier={float(outcome_control_trace_summary.get('sizing_multiplier', 1.0) or 1.0):.4f}"
                ),
                (
                    f"- portfolio_bias: tier={outcome_control_trace_summary.get('portfolio_bias_tier', 'neutral')} "
                    f"score_delta={float(outcome_control_trace_summary.get('portfolio_bias_score_delta', 0.0) or 0.0):.4f}"
                ),
                f"- top_reason_codes: {list(outcome_control_trace_summary.get('top_reason_codes') or [])}",
                "",
            ]

        rollout_recommendation_payload = dict(rollout_recommendation or {})
        rollout_recommendation_lines: list[str] = []
        if rollout_recommendation_payload:
            current_policy = dict(rollout_recommendation_payload.get("current_policy") or {})
            suggested_delta = dict(rollout_recommendation_payload.get("suggested_policy_delta") or {})
            top_modifier = dict(rollout_recommendation_payload.get("top_modifier") or {})
            rollout_recommendation_lines = [
                "## Outcome-First Rollout Recommendation",
                f"- available: {bool(rollout_recommendation_payload.get('available', False))}",
                f"- advisory_only: {bool(rollout_recommendation_payload.get('advisory_only', True))}",
                f"- family: {rollout_recommendation_payload.get('family', 'unknown')}",
                (
                    f"- recommendation: {rollout_recommendation_payload.get('recommendation', 'hold')} "
                    f"| confidence={rollout_recommendation_payload.get('confidence', 'low')} "
                    f"| maturity={rollout_recommendation_payload.get('maturity', 'thin_sample')}"
                ),
                f"- summary: {rollout_recommendation_payload.get('summary', '')}",
                (
                    f"- current_policy: live_enabled={bool(current_policy.get('live_enabled', False))} "
                    f"max_execution_mode={current_policy.get('max_execution_mode', 'SHADOW')} "
                    f"max_risk_r={float(current_policy.get('max_risk_r', 0.0) or 0.0):.4f} "
                    f"allowed_sessions={list(current_policy.get('allowed_sessions') or [])} "
                    f"min_quality_score={float(current_policy.get('min_quality_score', 0.0) or 0.0):.2f}"
                ),
                (
                    f"- suggested_policy_delta: action={suggested_delta.get('action', 'no_change')} "
                    f"suggested_max_execution_mode={suggested_delta.get('suggested_max_execution_mode', 'SHADOW')} "
                    f"suggested_max_risk_r={float(suggested_delta.get('suggested_max_risk_r', 0.0) or 0.0):.4f} "
                    f"change_hint={suggested_delta.get('change_hint', 'keep_current_policy')}"
                ),
                f"- reason_codes: {list(rollout_recommendation_payload.get('reason_codes') or [])}",
            ]
            if top_modifier:
                rollout_recommendation_lines.append(
                    "- top_modifier: "
                    f"axis={top_modifier.get('axis', 'n/a')} "
                    f"key={top_modifier.get('key', 'n/a')} "
                    f"state={top_modifier.get('state', 'neutral')}"
                )
            rollout_recommendation_lines.append("")

        strategy_lifecycle_payload = dict(strategy_lifecycle or {})
        strategy_lifecycle_lines: list[str] = []
        if strategy_lifecycle_payload:
            source_summary = dict(strategy_lifecycle_payload.get("source_summary") or {})
            strategy_lifecycle_lines = [
                "## Strategy Lifecycle",
                f"- available: {bool(strategy_lifecycle_payload.get('available', False))}",
                f"- advisory_only: {bool(strategy_lifecycle_payload.get('advisory_only', True))}",
                f"- family: {strategy_lifecycle_payload.get('family', 'unknown')}",
                (
                    f"- state: {strategy_lifecycle_payload.get('state', 'research')} "
                    f"| previous_state={strategy_lifecycle_payload.get('previous_state', 'research')} "
                    f"| transition_bias={strategy_lifecycle_payload.get('transition_bias', 'hold')} "
                    f"| confidence={strategy_lifecycle_payload.get('confidence', 'low')}"
                ),
                f"- summary: {strategy_lifecycle_payload.get('summary', '')}",
                f"- reason_codes: {list(strategy_lifecycle_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        promotion_governance_payload = dict(promotion_governance or {})
        promotion_governance_lines: list[str] = []
        if promotion_governance_payload:
            source_summary = dict(promotion_governance_payload.get("source_summary") or {})
            promotion_governance_lines = [
                "## Promotion Governance",
                f"- available: {bool(promotion_governance_payload.get('available', False))}",
                f"- advisory_only: {bool(promotion_governance_payload.get('advisory_only', True))}",
                f"- family: {promotion_governance_payload.get('family', 'unknown')}",
                (
                    f"- state: {promotion_governance_payload.get('state', 'defer')} "
                    f"| promotion_bias={promotion_governance_payload.get('promotion_bias', 'defer')} "
                    f"| target_posture={promotion_governance_payload.get('target_posture', 'keep_current')} "
                    f"| confidence={promotion_governance_payload.get('confidence', 'low')}"
                ),
                f"- summary: {promotion_governance_payload.get('summary', '')}",
                f"- reason_codes: {list(promotion_governance_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        promotion_review_queue_payload = dict(promotion_review_queue or {})
        promotion_review_queue_lines: list[str] = []
        if promotion_review_queue_payload:
            source_summary = dict(promotion_review_queue_payload.get("source_summary") or {})
            promotion_review_queue_lines = [
                "## Promotion Review Queue",
                f"- available: {bool(promotion_review_queue_payload.get('available', False))}",
                f"- advisory_only: {bool(promotion_review_queue_payload.get('advisory_only', True))}",
                (
                    f"- queue_state: {promotion_review_queue_payload.get('queue_state', 'empty_queue')} "
                    f"| headline_family={promotion_review_queue_payload.get('headline_family', '') or 'none'} "
                    f"| top_review_action={promotion_review_queue_payload.get('top_review_action', '') or 'none'}"
                ),
                f"- summary: {promotion_review_queue_payload.get('summary', '')}",
                f"- reason_codes: {list(promotion_review_queue_payload.get('reason_codes') or [])}",
                f"- review_queue: {list(promotion_review_queue_payload.get('review_queue') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        promotion_remediation_queue_payload = dict(promotion_remediation_queue or {})
        promotion_remediation_queue_lines: list[str] = []
        if promotion_remediation_queue_payload:
            source_summary = dict(promotion_remediation_queue_payload.get("source_summary") or {})
            promotion_remediation_queue_lines = [
                "## Promotion Remediation Queue",
                f"- available: {bool(promotion_remediation_queue_payload.get('available', False))}",
                f"- advisory_only: {bool(promotion_remediation_queue_payload.get('advisory_only', True))}",
                (
                    f"- queue_state: {promotion_remediation_queue_payload.get('queue_state', 'empty_queue')} "
                    f"| headline_family={promotion_remediation_queue_payload.get('headline_family', '') or 'none'} "
                    f"| top_remediation_action={promotion_remediation_queue_payload.get('top_remediation_action', '') or 'none'}"
                ),
                f"- summary: {promotion_remediation_queue_payload.get('summary', '')}",
                f"- reason_codes: {list(promotion_remediation_queue_payload.get('reason_codes') or [])}",
                f"- remediation_queue: {list(promotion_remediation_queue_payload.get('remediation_queue') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        promotion_clearance_tracker_payload = dict(promotion_clearance_tracker or {})
        promotion_clearance_tracker_lines: list[str] = []
        if promotion_clearance_tracker_payload:
            source_summary = dict(promotion_clearance_tracker_payload.get("source_summary") or {})
            promotion_clearance_tracker_lines = [
                "## Promotion Clearance Tracker",
                f"- available: {bool(promotion_clearance_tracker_payload.get('available', False))}",
                f"- advisory_only: {bool(promotion_clearance_tracker_payload.get('advisory_only', True))}",
                f"- family: {promotion_clearance_tracker_payload.get('family', 'unknown')}",
                (
                    f"- clearance_state: {promotion_clearance_tracker_payload.get('clearance_state', 'observe_only')} "
                    f"| clearance_bias={promotion_clearance_tracker_payload.get('clearance_bias', 'observe')} "
                    f"| confidence={promotion_clearance_tracker_payload.get('confidence', 'low')}"
                ),
                f"- summary: {promotion_clearance_tracker_payload.get('summary', '')}",
                f"- reason_codes: {list(promotion_clearance_tracker_payload.get('reason_codes') or [])}",
                (
                    "- guardrail_domains: "
                    f"remaining={list(promotion_clearance_tracker_payload.get('remaining_guardrail_domains') or [])} "
                    f"| cleared={list(promotion_clearance_tracker_payload.get('cleared_guardrail_domains') or [])}"
                ),
                f"- source_summary: {source_summary}",
                "",
            ]

        promotion_reopen_queue_payload = dict(promotion_reopen_queue or {})
        promotion_reopen_queue_lines: list[str] = []
        if promotion_reopen_queue_payload:
            source_summary = dict(promotion_reopen_queue_payload.get("source_summary") or {})
            promotion_reopen_queue_lines = [
                "## Promotion Reopen Queue",
                f"- available: {bool(promotion_reopen_queue_payload.get('available', False))}",
                f"- advisory_only: {bool(promotion_reopen_queue_payload.get('advisory_only', True))}",
                (
                    f"- queue_state: {promotion_reopen_queue_payload.get('queue_state', 'empty_queue')} "
                    f"| headline_family={promotion_reopen_queue_payload.get('headline_family', '') or 'none'} "
                    f"| top_reopen_action={promotion_reopen_queue_payload.get('top_reopen_action', '') or 'none'}"
                ),
                f"- summary: {promotion_reopen_queue_payload.get('summary', '')}",
                f"- reason_codes: {list(promotion_reopen_queue_payload.get('reason_codes') or [])}",
                f"- reopen_queue: {list(promotion_reopen_queue_payload.get('reopen_queue') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        promotion_decision_brief_payload = dict(promotion_decision_brief or {})
        promotion_decision_brief_lines: list[str] = []
        if promotion_decision_brief_payload:
            source_summary = dict(promotion_decision_brief_payload.get("source_summary") or {})
            promotion_decision_brief_lines = [
                "## Promotion Decision Brief",
                f"- available: {bool(promotion_decision_brief_payload.get('available', False))}",
                f"- advisory_only: {bool(promotion_decision_brief_payload.get('advisory_only', True))}",
                f"- family: {promotion_decision_brief_payload.get('family', 'unknown')}",
                (
                    f"- brief_state: {promotion_decision_brief_payload.get('brief_state', 'observe_case')} "
                    f"| decision_bias={promotion_decision_brief_payload.get('decision_bias', 'observe_only')} "
                    f"| target_posture={promotion_decision_brief_payload.get('target_posture', 'keep_current')} "
                    f"| confidence={promotion_decision_brief_payload.get('confidence', 'low')}"
                ),
                f"- summary: {promotion_decision_brief_payload.get('summary', '')}",
                f"- reason_codes: {list(promotion_decision_brief_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        auto_promotion_rollout_execution_payload = dict(auto_promotion_rollout_execution or {})
        auto_promotion_rollout_execution_lines: list[str] = []
        if auto_promotion_rollout_execution_payload:
            source_summary = dict(auto_promotion_rollout_execution_payload.get("source_summary") or {})
            auto_promotion_rollout_execution_lines = [
                "## Auto Promotion Rollout Execution",
                f"- available: {bool(auto_promotion_rollout_execution_payload.get('available', False))}",
                f"- advisory_only: {bool(auto_promotion_rollout_execution_payload.get('advisory_only', True))}",
                f"- target_family: {auto_promotion_rollout_execution_payload.get('target_family', 'unknown')}",
                (
                    f"- execution_stage: {auto_promotion_rollout_execution_payload.get('execution_stage', 'advisory_only')} "
                    f"| execution_bias={auto_promotion_rollout_execution_payload.get('execution_bias', 'keep_manual')} "
                    f"| action_domain={auto_promotion_rollout_execution_payload.get('action_domain', 'no_write_observe')}"
                ),
                (
                    f"- target_posture: {auto_promotion_rollout_execution_payload.get('target_posture', 'keep_current')} "
                    f"| write_scope={auto_promotion_rollout_execution_payload.get('write_scope', 'none')} "
                    f"| dry_run_only={bool(auto_promotion_rollout_execution_payload.get('dry_run_only', False))} "
                    f"| confidence={auto_promotion_rollout_execution_payload.get('confidence', 'low')}"
                ),
                f"- summary: {auto_promotion_rollout_execution_payload.get('summary', '')}",
                f"- reason_codes: {list(auto_promotion_rollout_execution_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        promotion_lifecycle_history_payload = dict(promotion_lifecycle_history or {})
        promotion_lifecycle_history_lines: list[str] = []
        if promotion_lifecycle_history_payload:
            source_summary = dict(promotion_lifecycle_history_payload.get("source_summary") or {})
            promotion_lifecycle_history_lines = [
                "## Promotion Lifecycle History",
                f"- available: {bool(promotion_lifecycle_history_payload.get('available', False))}",
                f"- advisory_only: {bool(promotion_lifecycle_history_payload.get('advisory_only', True))}",
                f"- family: {promotion_lifecycle_history_payload.get('family', 'unknown')}",
                (
                    f"- history_state: {promotion_lifecycle_history_payload.get('history_state', 'history_unavailable')} "
                    f"| latest_event_type={promotion_lifecycle_history_payload.get('latest_event_type', 'unknown')} "
                    f"| latest_event_ts={promotion_lifecycle_history_payload.get('latest_event_ts', '') or 'unknown'}"
                ),
                f"- event_count_30d: {int(promotion_lifecycle_history_payload.get('event_count_30d', 0) or 0)}",
                f"- recent_transitions: {list(promotion_lifecycle_history_payload.get('recent_transitions') or [])}",
                f"- summary: {promotion_lifecycle_history_payload.get('summary', '')}",
                f"- reason_codes: {list(promotion_lifecycle_history_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        research_promotion_operating_loop_payload = dict(research_promotion_operating_loop or {})
        research_promotion_operating_loop_lines: list[str] = []
        if research_promotion_operating_loop_payload:
            source_summary = dict(research_promotion_operating_loop_payload.get("source_summary") or {})
            research_promotion_operating_loop_lines = [
                "## Research Promotion Operating Loop",
                f"- available: {bool(research_promotion_operating_loop_payload.get('available', False))}",
                f"- advisory_only: {bool(research_promotion_operating_loop_payload.get('advisory_only', True))}",
                f"- family: {research_promotion_operating_loop_payload.get('family', 'unknown')}",
                (
                    f"- loop_state: {research_promotion_operating_loop_payload.get('loop_state', 'research_backlog')} "
                    f"| loop_bias={research_promotion_operating_loop_payload.get('loop_bias', 'observe_only')} "
                    f"| target_stage={research_promotion_operating_loop_payload.get('target_stage', 'research')} "
                    f"| confidence={research_promotion_operating_loop_payload.get('confidence', 'low')}"
                ),
                (
                    f"- recommended_action: {research_promotion_operating_loop_payload.get('recommended_action') or 'none'} "
                    f"| shadow_experiment_id={research_promotion_operating_loop_payload.get('shadow_experiment_id') or 'none'} "
                    f"| watchlist_ready={bool(research_promotion_operating_loop_payload.get('watchlist_ready', False))}"
                ),
                f"- summary: {research_promotion_operating_loop_payload.get('summary', '')}",
                f"- reason_codes: {list(research_promotion_operating_loop_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        positive_evidence_expansion_payload = dict(positive_evidence_expansion or {})
        positive_evidence_expansion_lines: list[str] = []
        if positive_evidence_expansion_payload:
            source_summary = dict(positive_evidence_expansion_payload.get("source_summary") or {})
            positive_evidence_expansion_lines = [
                "## Positive Evidence Expansion",
                f"- available: {bool(positive_evidence_expansion_payload.get('available', False))}",
                f"- advisory_only: {bool(positive_evidence_expansion_payload.get('advisory_only', True))}",
                f"- family: {positive_evidence_expansion_payload.get('family', 'unknown')}",
                (
                    f"- state: {positive_evidence_expansion_payload.get('state', 'not_ready')} "
                    f"| expansion_bias={positive_evidence_expansion_payload.get('expansion_bias', 'hold')} "
                    f"| confidence={positive_evidence_expansion_payload.get('confidence', 'low')}"
                ),
                f"- summary: {positive_evidence_expansion_payload.get('summary', '')}",
                f"- reason_codes: {list(positive_evidence_expansion_payload.get('reason_codes') or [])}",
                f"- source_summary: {source_summary}",
                "",
            ]

        outcome_bucket_granularity_payload = dict(outcome_bucket_granularity or {})
        outcome_bucket_granularity_lines: list[str] = []
        if outcome_bucket_granularity_payload:
            family_focus = dict(outcome_bucket_granularity_payload.get("family_focus") or {})
            top_condition_bucket = dict(outcome_bucket_granularity_payload.get("top_condition_bucket") or {})
            outcome_bucket_granularity_lines = [
                "## Outcome Bucket Granularity",
                f"- available: {bool(outcome_bucket_granularity_payload.get('available', False))}",
                f"- advisory_only: {bool(outcome_bucket_granularity_payload.get('advisory_only', True))}",
                (
                    f"- family_focus: key={family_focus.get('key', 'unknown')} "
                    f"closed={int(family_focus.get('closed', 0) or 0)} "
                    f"baseline_cost_profitable_rate_from_closed="
                    f"{float(family_focus.get('baseline_cost_profitable_rate_from_closed', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- top_condition: axis={outcome_bucket_granularity_payload.get('top_condition_axis', '') or 'none'} "
                    f"bucket={top_condition_bucket.get('key', 'none')} "
                    f"confidence={outcome_bucket_granularity_payload.get('confidence', 'low')}"
                ),
                f"- summary: {outcome_bucket_granularity_payload.get('summary', '')}",
                f"- reason_codes: {list(outcome_bucket_granularity_payload.get('reason_codes') or [])}",
                f"- condition_axes: {list(outcome_bucket_granularity_payload.get('condition_axes') or [])}",
                "",
            ]

        opportunity_capture_payload = dict(opportunity_capture or {})
        opportunity_capture_lines: list[str] = []
        if opportunity_capture_payload:
            dominant_bottleneck = dict(opportunity_capture_payload.get("dominant_bottleneck") or {})
            family_focus = dict(opportunity_capture_payload.get("family_focus") or {})
            regime_modifier = dict(opportunity_capture_payload.get("regime_modifier") or {})
            session_modifier = dict(opportunity_capture_payload.get("session_modifier") or {})
            opportunity_capture_lines = [
                "## Opportunity Capture",
                f"- available: {bool(opportunity_capture_payload.get('available', False))}",
                f"- advisory_only: {bool(opportunity_capture_payload.get('advisory_only', True))}",
                f"- summary: {opportunity_capture_payload.get('summary', '')}",
                f"- report_window_days: {int(opportunity_capture_payload.get('report_window_days', 0) or 0)}",
                f"- trades_per_day: {dict(opportunity_capture_payload.get('trades_per_day') or {})}",
                f"- capture_rates: {dict(opportunity_capture_payload.get('capture_rates') or {})}",
                f"- capture_gap: {dict(opportunity_capture_payload.get('capture_gap') or {})}",
                (
                    f"- dominant_bottleneck: stage={dominant_bottleneck.get('stage', 'unknown')} "
                    f"reason={dominant_bottleneck.get('reason', 'unknown')}"
                ),
                (
                    f"- family_focus: key={family_focus.get('key', 'unknown')} "
                    f"runtime_candidates={int(family_focus.get('runtime_candidates', 0) or 0)} "
                    f"submitted={int(family_focus.get('submitted', 0) or 0)} "
                    f"filled={int(family_focus.get('filled', 0) or 0)} "
                    f"closed={int(family_focus.get('closed', 0) or 0)}"
                ),
                (
                    f"- regime_modifier: key={regime_modifier.get('key', 'unknown')} "
                    f"state={regime_modifier.get('state', 'unavailable')}"
                ),
                (
                    f"- session_modifier: key={session_modifier.get('key', 'unknown')} "
                    f"state={session_modifier.get('state', 'unavailable')}"
                ),
                f"- blocked_mix: {dict(opportunity_capture_payload.get('blocked_mix') or {})}",
                "",
            ]

        capital_allocator_payload = dict(capital_allocator or {})
        capital_allocator_lines: list[str] = []
        if capital_allocator_payload:
            capital_allocator_lines = [
                "## Capital Allocator",
                f"- available: {bool(capital_allocator_payload.get('available', False))}",
                f"- advisory_only: {bool(capital_allocator_payload.get('advisory_only', False))}",
                f"- allocator_state: {capital_allocator_payload.get('allocator_state', 'neutral')}",
                f"- family_focus: {capital_allocator_payload.get('family_focus')}",
                f"- capital_pressure: {capital_allocator_payload.get('capital_pressure', 'neutral')}",
                f"- summary: {capital_allocator_payload.get('summary', '')}",
                f"- family_weights: {list(capital_allocator_payload.get('family_weights') or [])}",
                "",
            ]

        lock_payload = dict(strategy_v2_lock_validation or {})
        lock_metrics = dict(lock_payload.get("lock_metrics") or {})
        lock_before = dict(lock_metrics.get("before_lock") or {})
        lock_after = dict(lock_metrics.get("after_lock") or {})
        lock_comparison = dict(lock_payload.get("comparison") or {})
        lock_recommendation = dict(lock_payload.get("deployment_recommendation") or {})
        lock_lines: list[str] = []
        if lock_payload:
            lock_lines = [
                "## Transition / Shock Lock Comparison",
                f"- available: {bool(lock_payload.get('available', False))}",
                f"- comparison_axis: {lock_payload.get('comparison_axis', 'transition_shock_lock')}",
                f"- blocked_transition_trades: {int((lock_payload.get('sample_counts') or {}).get('blocked_transition_trades', 0))}",
                f"- blocked_shock_trades: {int((lock_payload.get('sample_counts') or {}).get('blocked_shock_trades', 0))}",
                f"- shock_clamped_trades: {int((lock_payload.get('sample_counts') or {}).get('shock_clamped_trades', 0))}",
                f"- keep_lock_enabled: {lock_recommendation.get('keep_lock_enabled', True)}",
                f"- recommendation_reason: {lock_recommendation.get('reason', 'not_available')}",
                (
                    f"- before_lock: trades={int(lock_before.get('trades', 0))}, ev={float(lock_before.get('ev', 0.0)):.4f}, "
                    f"p5={float(lock_before.get('p5_ev', 0.0)):.4f}, max_dd={float(lock_before.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(lock_before.get('ulcer_index', 0.0)):.4f}"
                ),
                (
                    f"- after_lock: trades={int(lock_after.get('trades', 0))}, ev={float(lock_after.get('ev', 0.0)):.4f}, "
                    f"p5={float(lock_after.get('p5_ev', 0.0)):.4f}, max_dd={float(lock_after.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(lock_after.get('ulcer_index', 0.0)):.4f}"
                ),
                (
                    f"- delta(after - before): ev={float(lock_comparison.get('ev', 0.0)):.4f}, "
                    f"p5={float(lock_comparison.get('p5_ev', 0.0)):.4f}, max_dd={float(lock_comparison.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(lock_comparison.get('ulcer_index', 0.0)):.4f}"
                ),
                "",
            ]

        pbo_dsr_trial_writer_payload = dict(strategy_v2_pbo_dsr_trial_writer or {})
        pbo_dsr_threshold_runner_payload = dict(strategy_v2_pbo_dsr_threshold_runner or {})
        pbo_dsr_payload = dict(strategy_v2_pbo_dsr_design or {})
        artifact_store_payload = dict(strategy_v2_pbo_dsr_artifact_store or {})
        pbo_dsr_metrics_payload = dict(strategy_v2_pbo_dsr_metrics or {})
        pbo = dict(pbo_dsr_payload.get("pbo") or {})
        dsr = dict(pbo_dsr_payload.get("dsr") or {})
        pbo_dsr_trial_writer_lines: list[str] = []
        if pbo_dsr_trial_writer_payload:
            writer_counts = dict(pbo_dsr_trial_writer_payload.get("sample_counts") or {})
            pbo_dsr_trial_writer_lines = [
                "## PBO / DSR Trial Writer",
                f"- available: {bool(pbo_dsr_trial_writer_payload.get('available', False))}",
                f"- implementation_status: {pbo_dsr_trial_writer_payload.get('implementation_status', 'not_available')}",
                f"- reason: {pbo_dsr_trial_writer_payload.get('reason', 'not_available')}",
                (
                    f"- counts: eligible_closed_trades={int(writer_counts.get('eligible_closed_trades', 0))}, "
                    f"candidate_trials={int(writer_counts.get('candidate_trials', 0))}, "
                    f"trial_runs_written={int(writer_counts.get('trial_runs_written', 0))}, "
                    f"fold_scores_written={int(writer_counts.get('fold_scores_written', 0))}, "
                    f"fold_count={int(writer_counts.get('fold_count', 0))}"
                ),
                f"- selected_trial_run_id: {pbo_dsr_trial_writer_payload.get('selected_trial_run_id', 'none')}",
                f"- parameter_families_present: {pbo_dsr_trial_writer_payload.get('parameter_families_present', [])}",
                "",
            ]
        pbo_dsr_threshold_runner_lines: list[str] = []
        if pbo_dsr_threshold_runner_payload:
            threshold_counts = dict(pbo_dsr_threshold_runner_payload.get("sample_counts") or {})
            pbo_dsr_threshold_runner_lines = [
                "## PBO / DSR Threshold Runner",
                f"- available: {bool(pbo_dsr_threshold_runner_payload.get('available', False))}",
                f"- implementation_status: {pbo_dsr_threshold_runner_payload.get('implementation_status', 'not_available')}",
                f"- reason: {pbo_dsr_threshold_runner_payload.get('reason', 'not_available')}",
                f"- selection_rule: {pbo_dsr_threshold_runner_payload.get('selection_rule', 'not_available')}",
                f"- lineage_namespace: {pbo_dsr_threshold_runner_payload.get('lineage_namespace', 'not_available')}",
                (
                    f"- counts: eligible_closed_trades={int(threshold_counts.get('eligible_closed_trades', 0))}, "
                    f"candidate_trials={int(threshold_counts.get('candidate_trials', 0))}, "
                    f"trial_runs_written={int(threshold_counts.get('trial_runs_written', 0))}, "
                    f"fold_scores_written={int(threshold_counts.get('fold_scores_written', 0))}, "
                    f"fold_count={int(threshold_counts.get('fold_count', 0))}"
                ),
                f"- selected_trial_run_id: {pbo_dsr_threshold_runner_payload.get('selected_trial_run_id', 'none')}",
                f"- parameter_families_present: {pbo_dsr_threshold_runner_payload.get('parameter_families_present', [])}",
                "",
            ]
        artifact_store_counts = dict(artifact_store_payload.get("counts") or {})
        artifact_store_snapshot = dict(artifact_store_payload.get("latest_snapshot") or {})
        artifact_store_selection_rule_counts = dict(artifact_store_payload.get("selection_rule_counts") or {})
        artifact_store_selection_universe_summary = dict(artifact_store_payload.get("selection_universe_summary") or {})
        artifact_store_lines: list[str] = []
        if artifact_store_payload:
            artifact_store_lines = [
                "## PBO / DSR Artifact Store",
                f"- artifact_store_ready: {bool(artifact_store_payload.get('artifact_store_ready', False))}",
                f"- available: {bool(artifact_store_payload.get('available', False))}",
                f"- metrics_available: {bool(artifact_store_payload.get('metrics_available', False))}",
                f"- implementation_status: {artifact_store_payload.get('implementation_status', 'not_available')}",
                f"- reason: {artifact_store_payload.get('reason', 'not_available')}",
                (
                    f"- counts: trial_runs={int(artifact_store_counts.get('trial_runs', 0))}, "
                    f"fold_scores={int(artifact_store_counts.get('fold_scores', 0))}, "
                    f"snapshots={int(artifact_store_counts.get('snapshots', 0))}"
                ),
                f"- parameter_families_present: {artifact_store_payload.get('parameter_families_present', [])}",
                f"- selection_rule_counts: {artifact_store_selection_rule_counts}",
                f"- selection_universe_summary: {artifact_store_selection_universe_summary}",
            ]
            if artifact_store_snapshot:
                artifact_store_lines.append(
                    (
                        f"- latest_snapshot: state={artifact_store_snapshot.get('computation_state', 'n/a')}, "
                        f"pbo_available={bool(artifact_store_snapshot.get('pbo_available', False))}, "
                        f"dsr_available={bool(artifact_store_snapshot.get('dsr_available', False))}"
                    )
                )
            artifact_store_lines.append("")
        pbo_dsr_lines: list[str] = []
        if pbo_dsr_payload:
            pbo_dsr_lines = [
                "## PBO / DSR Design Status",
                f"- design_ready: {bool(pbo_dsr_payload.get('design_ready', False))}",
                f"- available: {bool(pbo_dsr_payload.get('available', False))}",
                f"- implementation_status: {pbo_dsr_payload.get('implementation_status', 'not_available')}",
                f"- reason: {pbo_dsr_payload.get('reason', 'not_available')}",
                (
                    f"- PBO: method={pbo.get('method', 'CSCV')}, objective={pbo.get('objective_metric', 'out_of_sample_mean_ev')}, "
                    f"pass/warn/fail={float(pbo.get('pass_threshold', 0.20)):.2f}/{float(pbo.get('warn_threshold', 0.35)):.2f}/{float(pbo.get('fail_threshold', 0.35)):.2f}"
                ),
                (
                    f"- DSR: method={dsr.get('method', 'deflated_sharpe_ratio')}, "
                    f"min_threshold={float(dsr.get('min_threshold', 0.0)):.2f}"
                ),
            ]
            for item in list(pbo_dsr_payload.get("blocked_by") or []):
                pbo_dsr_lines.append(f"- blocker: {item}")
            pbo_dsr_lines.append("")
        pbo_dsr_metrics_lines: list[str] = []
        if pbo_dsr_metrics_payload:
            metric_pbo = dict(pbo_dsr_metrics_payload.get("pbo") or {})
            metric_dsr = dict(pbo_dsr_metrics_payload.get("dsr") or {})
            selected_trial = dict(pbo_dsr_metrics_payload.get("selected_trial") or {})
            lineage_audit = dict(pbo_dsr_metrics_payload.get("lineage_audit") or {})
            selection_universe_summary = dict(pbo_dsr_metrics_payload.get("selection_universe_summary") or {})
            recommendation = dict(pbo_dsr_metrics_payload.get("deployment_recommendation") or {})
            pbo_dsr_metrics_lines = [
                "## PBO / DSR Metrics",
                f"- available: {bool(pbo_dsr_metrics_payload.get('available', False))}",
                f"- metrics_complete: {bool(pbo_dsr_metrics_payload.get('metrics_complete', False))}",
                f"- reason: {pbo_dsr_metrics_payload.get('reason', 'not_available')}",
                f"- decision: {recommendation.get('decision', 'not_ready')}",
                f"- meets_protocol_gate: {recommendation.get('meets_protocol_gate', False)}",
                f"- selected_trial_run_id: {selected_trial.get('trial_run_id', 'none')}",
                f"- selected_trial_writer_source: {selected_trial.get('writer_source', 'unknown')}",
                f"- lineage_audit_status: {lineage_audit.get('audit_status', 'not_available')}",
                f"- lineage_audit_reason: {lineage_audit.get('reason', 'not_available')}",
                f"- lineage_mix_state: {lineage_audit.get('lineage_mix_state', 'no_lineage')}",
                f"- selection_universe_summary: {selection_universe_summary}",
                (
                    f"- PBO: value={metric_pbo.get('value')}, status={metric_pbo.get('status', 'not_available')}, "
                    f"eligible_folds={int(metric_pbo.get('eligible_folds', 0) or 0)}, overfit_folds={int(metric_pbo.get('overfit_folds', 0) or 0)}"
                ),
                (
                    f"- DSR: value={metric_dsr.get('value')}, probability={metric_dsr.get('probability')}, "
                    f"status={metric_dsr.get('status', 'not_available')}, benchmark_sharpe={metric_dsr.get('benchmark_sharpe')}, "
                    f"selection_universe_basis={metric_dsr.get('selection_universe_basis', 'combined_artifact_universe')}"
                ),
                "",
            ]

        stress_payload = dict(strategy_v2_stress_validation or {})
        stress_replay_lineage_payload = dict(strategy_v2_stress_replay_lineage or {})
        stress_replay_payload = dict(strategy_v2_stress_replay_assessment or {})
        stress_replay_runner_payload = dict(strategy_v2_stress_replay_runner_contract or {})
        stress_replay_writer_payload = dict(strategy_v2_stress_replay_lineage_writer or {})
        stress_replay_prototype_worker_payload = dict(strategy_v2_stress_replay_prototype_worker or {})
        stress_replay_output_artifacts = dict(stress_payload.get("replay_output_artifacts") or {})
        stress_replay_output_comparison = dict(stress_payload.get("replay_output_comparison") or {})
        stress_metrics = dict(stress_payload.get("stress_metrics") or {})
        stress_baseline = dict(stress_metrics.get("baseline_cost") or {})
        stress_after = dict(stress_metrics.get("stressed_cost") or {})
        stress_comparison = dict(stress_payload.get("comparison") or {})
        stress_scenario_metrics = dict(stress_payload.get("scenario_metrics") or {})
        stress_scenario_comparison = dict(stress_payload.get("scenario_comparison") or {})
        stress_recommendation = dict(stress_payload.get("deployment_recommendation") or {})
        stress_scenario_statuses = dict(stress_recommendation.get("scenario_statuses") or {})
        deployment_approval_template = self._deployment_approval_template(
            pbo_dsr_metrics_payload=pbo_dsr_metrics_payload,
            stress_payload=stress_payload,
            stress_replay_payload=stress_replay_payload,
        )
        stress_replay_lineage_lines: list[str] = []
        if stress_replay_lineage_payload:
            lineage_coverage = dict(stress_replay_lineage_payload.get("coverage") or {})
            lineage_fill_path = dict(stress_replay_lineage_payload.get("fill_path") or {})
            lineage_candle_path = dict(stress_replay_lineage_payload.get("candle_path") or {})
            stress_replay_lineage_lines = [
                "## Stress Replay Lineage",
                f"- available: {bool(stress_replay_lineage_payload.get('available', False))}",
                f"- runtime_inputs_ready: {bool(stress_replay_lineage_payload.get('runtime_inputs_ready', False))}",
                f"- reason: {stress_replay_lineage_payload.get('reason', 'not_available')}",
                f"- execution_fill_coverage: {float(lineage_coverage.get('execution_fill_coverage', 0.0)):.4f}",
                f"- latency_candle_coverage: {float(lineage_coverage.get('latency_candle_coverage', 0.0)):.4f}",
                f"- candle_path_coverage: {float(lineage_coverage.get('candle_path_coverage', 0.0)):.4f}",
                f"- estimate_only_share: {float(lineage_coverage.get('estimate_only_share', 0.0)):.4f}",
                f"- entry_anchor_sources: {lineage_fill_path.get('entry_anchor_sources', {})}",
                f"- exit_anchor_sources: {lineage_fill_path.get('exit_anchor_sources', {})}",
                f"- avg_path_coverage_ratio: {float(lineage_candle_path.get('avg_path_coverage_ratio', 0.0)):.4f}",
                "",
            ]
        stress_replay_recommendation = dict(stress_replay_payload.get("deployment_recommendation") or {})
        stress_lines: list[str] = []
        if stress_payload:
            stress_lines = [
                "## Stressed Cost Comparison",
                f"- available: {bool(stress_payload.get('available', False))}",
                f"- comparison_axis: {stress_payload.get('comparison_axis', 'baseline_vs_stressed_cost')}",
                f"- execution_data_trades: {int((stress_payload.get('sample_counts') or {}).get('execution_data_trades', 0))}",
                f"- estimate_only_trades: {int((stress_payload.get('sample_counts') or {}).get('estimate_only_trades', 0))}",
                f"- latency_reference_trades: {int((stress_payload.get('sample_counts') or {}).get('latency_reference_trades', 0))}",
                f"- shock_regime_trades: {int((stress_payload.get('sample_counts') or {}).get('shock_regime_trades', 0))}",
                f"- stress_pass: {stress_recommendation.get('stress_pass', False)}",
                f"- recommendation_reason: {stress_recommendation.get('reason', 'not_available')}",
                f"- worst_scenario: {stress_recommendation.get('worst_scenario', 'stressed_cost')}",
                f"- worst_scenario_source: {stress_recommendation.get('worst_scenario_source', 'stressed_cost')}",
                f"- replay_gate_applied: {bool(stress_recommendation.get('replay_gate_applied', False))}",
                f"- replay_gate_reason: {stress_recommendation.get('replay_gate_reason', 'approximation_only')}",
                f"- divergence_gate_applied: {bool(stress_recommendation.get('divergence_gate_applied', False))}",
                f"- divergence_problem_scenarios: {stress_recommendation.get('divergence_problem_scenarios', [])}",
                f"- worst_divergence_scenario: {stress_recommendation.get('worst_divergence_scenario')}",
                (
                    f"- baseline_cost: trades={int(stress_baseline.get('trades', 0))}, ev={float(stress_baseline.get('ev', 0.0)):.4f}, "
                    f"p5={float(stress_baseline.get('p5_ev', 0.0)):.4f}, max_dd={float(stress_baseline.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(stress_baseline.get('ulcer_index', 0.0)):.4f}"
                ),
                (
                    f"- stressed_cost: trades={int(stress_after.get('trades', 0))}, ev={float(stress_after.get('ev', 0.0)):.4f}, "
                    f"p5={float(stress_after.get('p5_ev', 0.0)):.4f}, max_dd={float(stress_after.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(stress_after.get('ulcer_index', 0.0)):.4f}"
                ),
                (
                    f"- delta(stressed - baseline): ev={float(stress_comparison.get('ev', 0.0)):.4f}, "
                    f"p5={float(stress_comparison.get('p5_ev', 0.0)):.4f}, max_dd={float(stress_comparison.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(stress_comparison.get('ulcer_index', 0.0)):.4f}"
                ),
            ]
            for scenario_name in ("latency_plus_1_bar", "partial_fills_only", "shock_concentration"):
                metrics = dict(stress_scenario_metrics.get(scenario_name) or {})
                delta = dict(stress_scenario_comparison.get(scenario_name) or {})
                scenario_status = dict(stress_scenario_statuses.get(scenario_name) or {})
                replay_row = dict((stress_replay_output_artifacts.get("scenario_outputs") or {}).get(scenario_name) or {})
                replay_summary = dict(replay_row.get("summary") or {})
                replay_delta = dict(stress_replay_output_comparison.get(scenario_name) or replay_row.get("comparison_to_approximation") or {})
                effective_metrics = (
                    replay_summary if scenario_status.get("source") == "replay_output" and replay_summary else metrics
                )
                stress_lines.append(
                    f"- {scenario_name}: status={scenario_status.get('status', 'n/a')}, "
                    f"source={scenario_status.get('source', 'approximation')}, "
                    f"reason={scenario_status.get('reason', 'n/a')}, ev={float(effective_metrics.get('ev', 0.0)):.4f}, "
                    f"p5={float(effective_metrics.get('p5_ev', 0.0)):.4f}, max_dd={float(effective_metrics.get('max_drawdown', 0.0)):.4f}, "
                    f"delta_ev={float((replay_delta if scenario_status.get('source') == 'replay_output' else delta).get('ev', 0.0)):.4f}, "
                    f"delta_max_dd={float((replay_delta if scenario_status.get('source') == 'replay_output' else delta).get('max_drawdown', 0.0)):.4f}"
                )
                if replay_row:
                    stress_lines.append(
                        f"  replay_output: available={bool(replay_row.get('available', False))}, "
                        f"reason={replay_row.get('reason', 'not_available')}, ev={float(replay_summary.get('ev', 0.0)):.4f}, "
                        f"max_dd={float(replay_summary.get('max_drawdown', 0.0)):.4f}, "
                        f"delta_replay_minus_approx_ev={float(replay_delta.get('ev', 0.0)):.4f}, "
                        f"delta_replay_minus_approx_max_dd={float(replay_delta.get('max_drawdown', 0.0)):.4f}"
                    )
            stress_lines.extend(
                [
                    f"- replay_output_artifacts_available: {bool(stress_replay_output_artifacts.get('available', False))}",
                    f"- replay_output_artifacts_reason: {stress_replay_output_artifacts.get('reason', 'not_available')}",
                    f"- replay_output_summary_counts: {stress_replay_output_artifacts.get('summary_counts', {})}",
                ]
            )
            stress_lines.append("")

        stress_replay_lines: list[str] = []
        if stress_replay_payload:
            coverage = dict(stress_replay_payload.get("coverage") or {})
            scenario_evidence = dict(stress_replay_payload.get("scenario_evidence") or {})
            true_runner_readiness = dict(stress_replay_payload.get("true_runner_readiness") or {})
            stress_replay_lines = [
                "## Stress Replay Assessment",
                f"- available: {bool(stress_replay_payload.get('available', False))}",
                f"- full_replay_ready: {bool(stress_replay_payload.get('full_replay_ready', False))}",
                f"- replacement_recommended: {bool(stress_replay_payload.get('replacement_recommended', False))}",
                f"- true_runner_ready: {bool(true_runner_readiness.get('true_runner_ready', False))}",
                f"- true_runner_stage: {true_runner_readiness.get('stage', 'prototype_only')}",
                f"- decision: {stress_replay_recommendation.get('decision', 'keep_approximation')}",
                f"- priority: {stress_replay_recommendation.get('priority', 'low')}",
                f"- reason: {stress_replay_recommendation.get('reason', 'not_available')}",
                f"- true_runner_promotion_ready: {bool(stress_replay_recommendation.get('true_runner_promotion_ready', False))}",
                f"- true_runner_promotion_status: {stress_replay_recommendation.get('true_runner_promotion_status', 'NOT_APPLICABLE')}",
                f"- true_runner_promotion_action: {stress_replay_recommendation.get('true_runner_promotion_action', 'keep_current_path')}",
                f"- true_runner_promotion_reason: {stress_replay_recommendation.get('true_runner_promotion_reason', 'not_available')}",
                f"- threshold_lineage_audit_status: {stress_replay_recommendation.get('threshold_lineage_audit_status', 'not_available')}",
                f"- selected_trial_writer_source: {stress_replay_recommendation.get('selected_trial_writer_source', 'unknown')}",
                f"- replay_output_lineage_alignment_status: {stress_replay_recommendation.get('replay_output_lineage_alignment_status', 'NOT_AVAILABLE')}",
                f"- replay_output_lineage_alignment_reason: {stress_replay_recommendation.get('replay_output_lineage_alignment_reason', 'not_available')}",
                f"- replay_output_lineage_compared_scenarios: {stress_replay_recommendation.get('replay_output_lineage_compared_scenarios', [])}",
                (
                    f"- replay_output_lineage_input_trade_rows: "
                    f"{int(stress_replay_recommendation.get('replay_output_lineage_input_trade_rows', 0) or 0)}"
                ),
                (
                    f"- coverage: execution_fill={float(coverage.get('execution_fill_coverage', 0.0)):.4f}, "
                    f"latency_candle={float(coverage.get('latency_candle_coverage', 0.0)):.4f}, "
                    f"candle_path={float(coverage.get('candle_path_coverage', 0.0)):.4f}, "
                    f"estimate_only={float(coverage.get('estimate_only_share', 0.0)):.4f}"
                ),
                f"- degraded_scenarios: {scenario_evidence.get('degraded_scenarios', [])}",
                f"- catastrophic_scenarios: {scenario_evidence.get('catastrophic_scenarios', [])}",
                f"- worst_scenario: {scenario_evidence.get('worst_scenario', 'stressed_cost')}",
                "",
            ]

        stress_replay_runner_lines: list[str] = []
        if stress_replay_runner_payload:
            readiness = dict(stress_replay_runner_payload.get("readiness") or {})
            runner_contract = dict(stress_replay_runner_payload.get("runner_contract") or {})
            batching = dict(runner_contract.get("batching") or {})
            true_runner_readiness = dict(stress_replay_runner_payload.get("true_runner_readiness") or {})
            stress_replay_runner_lines = [
                "## Stress Replay Runner Contract",
                f"- available: {bool(stress_replay_runner_payload.get('available', False))}",
                f"- runtime_job_ready: {bool(stress_replay_runner_payload.get('runtime_job_ready', False))}",
                f"- implementation_status: {stress_replay_runner_payload.get('implementation_status', 'not_available')}",
                f"- reason: {stress_replay_runner_payload.get('reason', 'not_available')}",
                f"- priority: {readiness.get('priority', 'low')}",
                f"- ready_scenarios: {readiness.get('ready_scenarios', [])}",
                f"- blocked_scenarios: {readiness.get('blocked_scenarios', [])}",
                f"- suggested_total_jobs: {int(readiness.get('suggested_total_jobs', 0) or 0)}",
                f"- true_runner_ready: {bool(true_runner_readiness.get('true_runner_ready', False))}",
                f"- true_runner_stage: {true_runner_readiness.get('stage', 'prototype_only')}",
                (
                    f"- batching: target={int(batching.get('target_trades_per_job', 0) or 0)}, "
                    f"min={int(batching.get('min_trades_per_job', 0) or 0)}, "
                    f"max_parallel={int(batching.get('max_parallel_jobs', 0) or 0)}"
                ),
                "",
            ]

        stress_replay_writer_lines: list[str] = []
        if stress_replay_writer_payload:
            writer_counts = dict(stress_replay_writer_payload.get("sample_counts") or {})
            stress_replay_writer_lines = [
                "## Stress Replay Lineage Writer",
                f"- available: {bool(stress_replay_writer_payload.get('available', False))}",
                f"- artifacts_written: {bool(stress_replay_writer_payload.get('artifacts_written', False))}",
                f"- runtime_job_ready: {bool(stress_replay_writer_payload.get('runtime_job_ready', False))}",
                f"- implementation_status: {stress_replay_writer_payload.get('implementation_status', 'not_available')}",
                f"- reason: {stress_replay_writer_payload.get('reason', 'not_available')}",
                f"- trade_rows_written: {int(writer_counts.get('trade_rows_written', 0) or 0)}",
                f"- batches_written: {int(writer_counts.get('batches_written', 0) or 0)}",
                f"- scenarios_written: {int(writer_counts.get('scenarios_written', 0) or 0)}",
                "",
            ]

        stress_replay_prototype_worker_lines: list[str] = []
        if stress_replay_prototype_worker_payload:
            prototype_counts = dict(stress_replay_prototype_worker_payload.get("sample_counts") or {})
            stress_replay_prototype_worker_lines = [
                "## Stress Replay Prototype Worker",
                f"- available: {bool(stress_replay_prototype_worker_payload.get('available', False))}",
                f"- executed: {bool(stress_replay_prototype_worker_payload.get('executed', False))}",
                f"- runtime_job_ready: {bool(stress_replay_prototype_worker_payload.get('runtime_job_ready', False))}",
                f"- reason: {stress_replay_prototype_worker_payload.get('reason', 'not_available')}",
                f"- ready_scenarios: {int(prototype_counts.get('ready_scenarios', 0) or 0)}",
                f"- executed_scenarios: {int(prototype_counts.get('executed_scenarios', 0) or 0)}",
                f"- input_batches_read: {int(prototype_counts.get('input_batches_read', 0) or 0)}",
                f"- replay_trade_rows_written: {int(prototype_counts.get('replay_trade_rows_written', 0) or 0)}",
                "",
            ]

        performance_decomposition_summary = self._performance_decomposition_summary(
            execution_quality=execution_quality,
            strategy_v2_validation=v2_payload,
            strategy_v2_stress_validation=stress_payload,
        )
        performance_decomposition_lines: list[str] = []
        if performance_decomposition_summary:
            perf_family = dict(performance_decomposition_summary.get("family") or {})
            perf_regime = dict(performance_decomposition_summary.get("regime") or {})
            perf_session = dict(performance_decomposition_summary.get("session") or {})
            perf_entry_model = dict(performance_decomposition_summary.get("entry_model") or {})
            perf_cost = dict(performance_decomposition_summary.get("cost") or {})

            def _bucket_line(label: str, payload: dict[str, Any], metric_key: str, sample_key: str) -> str | None:
                if not payload:
                    return None
                return (
                    f"- {label}: {payload.get('name')} | {metric_key}={float(payload.get(metric_key, 0.0) or 0.0):.4f} | "
                    f"{sample_key}={int(payload.get(sample_key, 0) or 0)}"
                )

            performance_decomposition_lines = ["## Performance Decomposition"]
            for item in [
                _bucket_line("family_best_ev", dict(perf_family.get("best_ev") or {}), "ev", "trades"),
                _bucket_line("family_worst_ev", dict(perf_family.get("worst_ev") or {}), "ev", "trades"),
                _bucket_line(
                    "family_highest_forced_exit_rate",
                    dict(perf_family.get("highest_forced_exit_rate") or {}),
                    "forced_exit_rate",
                    "closed",
                ),
                _bucket_line(
                    "family_highest_information_failure_rate",
                    dict(perf_family.get("highest_information_failure_rate") or {}),
                    "information_failure_rate",
                    "closed",
                ),
                _bucket_line("regime_best_ev", dict(perf_regime.get("best_ev") or {}), "ev", "trades"),
                _bucket_line("regime_worst_ev", dict(perf_regime.get("worst_ev") or {}), "ev", "trades"),
                _bucket_line("session_best_ev", dict(perf_session.get("best_ev") or {}), "ev", "trades"),
                _bucket_line("session_worst_ev", dict(perf_session.get("worst_ev") or {}), "ev", "trades"),
                _bucket_line("entry_model_best_fill_rate", dict(perf_entry_model.get("best_fill_rate") or {}), "fill_rate", "plans"),
                _bucket_line(
                    "entry_model_worst_fill_rate",
                    dict(perf_entry_model.get("worst_fill_rate") or {}),
                    "fill_rate",
                    "plans",
                ),
                _bucket_line(
                    "entry_model_worst_slippage_bps",
                    dict(perf_entry_model.get("worst_slippage_bps") or {}),
                    "avg_slippage_bps",
                    "plans",
                ),
            ]:
                if item:
                    performance_decomposition_lines.append(item)
            if perf_cost:
                performance_decomposition_lines.append(
                    (
                        f"- post_cost_ev: baseline={float(perf_cost.get('baseline_cost_ev', 0.0) or 0.0):.4f} | "
                        f"stressed={float(perf_cost.get('stressed_cost_ev', 0.0) or 0.0):.4f} | "
                        f"delta={float(perf_cost.get('delta_ev_stressed_minus_baseline', 0.0) or 0.0):.4f} | "
                        f"worst_scenario={perf_cost.get('worst_scenario')} | "
                        f"source={perf_cost.get('worst_scenario_source')}"
                    )
                )
            for idx, focus in enumerate(list(performance_decomposition_summary.get("tuning_focus") or []), start=1):
                performance_decomposition_lines.append(
                    (
                        f"- focus_{idx}: {focus.get('focus')} -> {focus.get('bucket')} | "
                        f"{focus.get('metric')}={float(focus.get('value', 0.0) or 0.0):.4f} | "
                        f"samples={int(focus.get('samples', 0) or 0)}"
                    )
                )
            performance_decomposition_lines.append("")

        outcome_attribution = build_outcome_attribution(
            score_to_outcome_funnel=score_to_outcome_payload,
            performance_decomposition_summary=performance_decomposition_summary,
            execution_friction_measurement=execution_friction_measurement_payload,
        )
        outcome_attribution_summary = summarize_outcome_attribution(outcome_attribution)
        outcome_attribution_lines: list[str] = []
        if outcome_attribution_summary:
            outcome_attribution_lines = [
                "## Outcome Attribution",
                f"- available: {bool(outcome_attribution_summary.get('available', False))}",
                f"- advisory_only: {bool(outcome_attribution_summary.get('advisory_only', True))}",
                (
                    f"- confidence: {outcome_attribution_summary.get('confidence', 'low')} | "
                    f"closed_trade_count={int(outcome_attribution_summary.get('closed_trade_count', 0) or 0)} | "
                    f"strongest_drag_source={outcome_attribution_summary.get('strongest_drag_source', 'none')}"
                ),
                (
                    f"- components_r: strategy={float(outcome_attribution_summary.get('strategy_component_r', 0.0) or 0.0):.4f}, "
                    f"execution={float(outcome_attribution_summary.get('execution_component_r', 0.0) or 0.0):.4f}, "
                    f"condition={float(outcome_attribution_summary.get('condition_component_r', 0.0) or 0.0):.4f}, "
                    f"fill_capture_gap={float(outcome_attribution_summary.get('fill_capture_gap_r', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- expected_vs_realized_r: expected_closed={float(outcome_attribution_summary.get('closed_expected_r', 0.0) or 0.0):.4f}, "
                    f"post_cost_closed={float(outcome_attribution_summary.get('closed_post_cost_realized_r', 0.0) or 0.0):.4f}, "
                    f"delta={float(outcome_attribution_summary.get('closed_post_cost_delta_r', 0.0) or 0.0):.4f}"
                ),
                f"- summary: {outcome_attribution_summary.get('summary', '')}",
                f"- reason_codes: {list(outcome_attribution_summary.get('reason_codes') or [])}",
                f"- source_summary: {dict(outcome_attribution_summary.get('source_summary') or {})}",
                "",
            ]

        edge_experiment_review = build_edge_experiment_review(score_to_outcome_funnel=score_to_outcome_payload)
        edge_experiment_summary = summarize_edge_experiment_review(edge_experiment_review)
        review_followup_ledger_summary = summarize_split_review_followup_ledger(
            symbol=symbol,
            universe=str(getattr(self.settings, "universe_name", "usdc_perp_top30") or "usdc_perp_top30"),
        )
        edge_experiment_lines: list[str] = []
        if edge_experiment_summary:
            true_edge = dict(edge_experiment_summary.get("true_edge") or {})
            entry_timing = dict(edge_experiment_summary.get("entry_timing_experiment") or {})
            execution_style = dict(edge_experiment_summary.get("execution_style_experiment") or {})
            regime_breakdown = dict(edge_experiment_summary.get("regime_edge_breakdown") or {})
            experiment_sequence = dict(edge_experiment_summary.get("experiment_sequence") or {})
            edge_experiment_lines = [
                "## Edge Experiment Review",
                f"- available: {bool(edge_experiment_summary.get('available', False))}",
                f"- advisory_only: {bool(edge_experiment_summary.get('advisory_only', True))}",
                (
                    f"- edge_state: {edge_experiment_summary.get('edge_state', 'insufficient_edge_measurement')} | "
                    f"closed_trade_count={int(edge_experiment_summary.get('closed_trade_count', 0) or 0)} | "
                    f"true_edge_ratio={float(edge_experiment_summary.get('true_edge_ratio', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- edge_windows: recent={float(edge_experiment_summary.get('recent_true_edge_ratio', 0.0) or 0.0):.4f}, "
                    f"prior={float(edge_experiment_summary.get('prior_true_edge_ratio', 0.0) or 0.0):.4f}, "
                    f"decay={float(edge_experiment_summary.get('edge_decay_rate', 0.0) or 0.0):+.4f}, "
                    f"stability={float(edge_experiment_summary.get('edge_stability', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- entry_timing_experiment: available={bool(edge_experiment_summary.get('entry_timing_available', False))} | "
                    f"comparison_ready={bool(edge_experiment_summary.get('entry_timing_comparison_ready', False))} | "
                    f"preferred={edge_experiment_summary.get('entry_timing_preferred_variant', 'none')} | "
                    f"reason={edge_experiment_summary.get('entry_timing_recommendation_reason', 'not_available')}"
                ),
                (
                    f"- execution_style_experiment: available={bool(edge_experiment_summary.get('execution_style_available', False))} | "
                    f"comparison_ready={bool(edge_experiment_summary.get('execution_style_comparison_ready', False))} | "
                    f"preferred={edge_experiment_summary.get('execution_style_preferred_variant', 'none')} | "
                    f"reason={edge_experiment_summary.get('execution_style_recommendation_reason', 'not_available')}"
                ),
                (
                    f"- sample_progress: state={edge_experiment_summary.get('sample_maturity_state', 'unknown')} | "
                    f"next_target_closed_trades={int(edge_experiment_summary.get('next_sample_target_closed_trades', 0) or 0)} | "
                    f"remaining={int(edge_experiment_summary.get('remaining_closed_trades_to_next_target', 0) or 0)}"
                ),
                (
                    f"- edge_proof: state={dict(edge_experiment_summary.get('edge_proof_posture') or {}).get('state', 'unknown')} | "
                    f"claim={dict(edge_experiment_summary.get('edge_proof_posture') or {}).get('claim_state', 'unknown')} | "
                    f"goal_closed_trades={int(edge_experiment_summary.get('edge_proof_goal_closed_trades', 0) or 0)} | "
                    f"remaining_to_goal={int(edge_experiment_summary.get('remaining_closed_trades_to_edge_proof_goal', 0) or 0)}"
                ),
                (
                    f"- operating_discipline: state={dict(edge_experiment_summary.get('operating_discipline') or {}).get('discipline_state', 'unknown')} | "
                    f"framework={dict(edge_experiment_summary.get('operating_discipline') or {}).get('framework_quality_state', 'framework_ready')} | "
                    f"mode={dict(edge_experiment_summary.get('operating_discipline') or {}).get('system_mode', 'operate_and_experiment')} | "
                    f"primary_goal={dict(edge_experiment_summary.get('operating_discipline') or {}).get('primary_goal', 'find_first_verified_edge')} | "
                    f"improvement_priority={dict(edge_experiment_summary.get('operating_discipline') or {}).get('improvement_priority', 'prove_single_edge_before_density_or_strategy_expansion')} | "
                    f"evaluation_focus={dict(edge_experiment_summary.get('operating_discipline') or {}).get('evaluation_focus', 'after_cost_edge_only')} | "
                    f"min_closed_trades={int(dict(edge_experiment_summary.get('operating_discipline') or {}).get('minimum_closed_trades_for_edge_evaluation', 0) or 0)} | "
                    f"profit_claim_allowed={bool(dict(edge_experiment_summary.get('operating_discipline') or {}).get('profit_claim_allowed', False))} | "
                    f"structure_change_review_allowed={bool(dict(edge_experiment_summary.get('operating_discipline') or {}).get('structure_change_review_allowed', False))} | "
                    f"loss_driven_rewrite_allowed={bool(dict(edge_experiment_summary.get('operating_discipline') or {}).get('loss_driven_rewrite_allowed', False))} | "
                    f"early_loss_embargo_active={bool(dict(edge_experiment_summary.get('operating_discipline') or {}).get('early_loss_rewrite_embargo_active', False))} | "
                    f"rollout_expansion_allowed={bool(dict(edge_experiment_summary.get('operating_discipline') or {}).get('rollout_expansion_allowed', False))} | "
                    f"signal_density_review_allowed={bool(dict(edge_experiment_summary.get('operating_discipline') or {}).get('signal_density_control_review_allowed', False))} | "
                    f"multi_strategy_expansion_review_allowed={bool(dict(edge_experiment_summary.get('operating_discipline') or {}).get('multi_strategy_expansion_review_allowed', False))} | "
                    f"single_experiment_only={bool(dict(edge_experiment_summary.get('operating_discipline') or {}).get('single_experiment_only', True))}"
                ),
                (
                    f"- experiment_sequence: state={experiment_sequence.get('state', 'unknown')} | "
                    f"entry_timing_locked={bool(experiment_sequence.get('entry_timing_locked', False))} | "
                    f"execution_style_locked={bool(experiment_sequence.get('execution_style_locked', False))} | "
                    f"exit_optimization_allowed={bool(experiment_sequence.get('exit_optimization_allowed', False))} | "
                    f"current_priority={experiment_sequence.get('current_priority_experiment', 'unknown')}:{experiment_sequence.get('current_priority_action', 'unknown')}"
                ),
                f"- experiment_sequence_summary: {experiment_sequence.get('summary', '')}",
                (
                    f"- regime_breakdown: dependency={edge_experiment_summary.get('regime_dependency_state', 'not_available')} | "
                    f"strongest={edge_experiment_summary.get('strongest_regime', 'none')}:{float(edge_experiment_summary.get('strongest_regime_true_edge_ratio', 0.0) or 0.0):.4f} | "
                    f"weakest={edge_experiment_summary.get('weakest_regime', 'none')}:{float(edge_experiment_summary.get('weakest_regime_true_edge_ratio', 0.0) or 0.0):.4f}"
                ),
                f"- daily_edge_kpis: {dict(edge_experiment_summary.get('daily_edge_kpis') or {})}",
                f"- operating_discipline_summary: {dict(edge_experiment_summary.get('operating_discipline') or {}).get('summary', '')}",
                f"- summary: {edge_experiment_summary.get('summary', '')}",
                f"- reason_codes: {list(edge_experiment_summary.get('reason_codes') or [])}",
                f"- source_summary: {dict(edge_experiment_summary.get('source_summary') or {})}",
            ]
            for label, payload in (
                ("entry_timing_lhs", dict(entry_timing.get("lhs") or {})),
                ("entry_timing_rhs", dict(entry_timing.get("rhs") or {})),
                ("execution_style_lhs", dict(execution_style.get("lhs") or {})),
                ("execution_style_rhs", dict(execution_style.get("rhs") or {})),
            ):
                if payload:
                    edge_experiment_lines.append(
                        f"- {label}: key={payload.get('key')} submitted={int(payload.get('submitted', 0) or 0)} "
                        f"filled={int(payload.get('filled', 0) or 0)} closed={int(payload.get('closed', 0) or 0)} "
                        f"capture_ratio_r={float(payload.get('capture_ratio_r', 0.0) or 0.0):.4f} "
                        f"true_edge_ratio={float(payload.get('true_edge_ratio', 0.0) or 0.0):.4f}"
                    )
            if true_edge:
                edge_experiment_lines.append(
                    f"- window_closed_counts: recent={int(dict(true_edge.get('recent_window') or {}).get('closed', 0) or 0)}, "
                    f"prior={int(dict(true_edge.get('prior_window') or {}).get('closed', 0) or 0)}"
                )
            for idx, payload in enumerate(list(regime_breakdown.get("rows") or [])[:3], start=1):
                edge_experiment_lines.append(
                    f"- regime_{idx}: key={payload.get('key')} closed={int(payload.get('closed', 0) or 0)} "
                    f"capture_ratio_r={float(payload.get('capture_ratio_r', 0.0) or 0.0):.4f} "
                    f"true_edge_ratio={float(payload.get('true_edge_ratio', 0.0) or 0.0):.4f}"
                )
            edge_experiment_lines.append("")

        edge_evolution_summary = summarize_edge_evolution_rule(
            build_edge_evolution_rule(
                edge_experiment_review=edge_experiment_summary,
                rollout_recommendation=rollout_recommendation_payload,
                strategy_lifecycle=strategy_lifecycle_payload,
                kill_condition_automation=kill_condition_automation_payload,
                review_followup_ledger=review_followup_ledger_summary,
            )
        )
        edge_evolution_lines: list[str] = []
        if edge_evolution_summary:
            edge_evolution_lines = [
                "## Edge Evolution Rule",
                f"- available: {bool(edge_evolution_summary.get('available', False))}",
                f"- advisory_only: {bool(edge_evolution_summary.get('advisory_only', True))}",
                (
                    f"- evolution_state: {edge_evolution_summary.get('evolution_state', 'insufficient_sample')} | "
                    f"recommended_action={edge_evolution_summary.get('recommended_action', 'keep_current_baseline')} | "
                    f"allocation_bias={edge_evolution_summary.get('allocation_bias', 'hold_current_baseline')} | "
                    f"confidence={edge_evolution_summary.get('confidence', 'low')}"
                ),
                (
                    f"- edge_basis: true_edge_ratio={float(edge_evolution_summary.get('true_edge_ratio', 0.0) or 0.0):.4f} | "
                    f"edge_decay_rate={float(edge_evolution_summary.get('edge_decay_rate', 0.0) or 0.0):+.4f} | "
                    f"closed_trade_count={int(edge_evolution_summary.get('closed_trade_count', 0) or 0)} | "
                    f"kill_review_triggered={bool(edge_evolution_summary.get('kill_review_triggered', False))}"
                ),
                (
                    f"- regime_guard: state={edge_evolution_summary.get('regime_guard_state', 'not_applicable')} | "
                    f"strongest={edge_evolution_summary.get('strongest_regime', 'none')} | "
                    f"weakest={edge_evolution_summary.get('weakest_regime', 'none')}:{float(edge_evolution_summary.get('weakest_regime_true_edge_ratio', 0.0) or 0.0):.4f}"
                ),
                (
                    f"- promotion_candidate: axis={edge_evolution_summary.get('promotion_candidate_axis', 'none')} | "
                    f"variant={edge_evolution_summary.get('promotion_candidate_variant', 'none')} | "
                    f"reason={edge_evolution_summary.get('promotion_candidate_reason', 'not_available')}"
                ),
                f"- summary: {edge_evolution_summary.get('summary', '')}",
                f"- reason_codes: {list(edge_evolution_summary.get('reason_codes') or [])}",
                f"- source_summary: {dict(edge_evolution_summary.get('source_summary') or {})}",
                "",
            ]
        review_followup_ledger_lines: list[str] = []
        if review_followup_ledger_summary:
            review_followup_ledger_lines = [
                "## Review Followup Ledger",
                f"- available: {bool(review_followup_ledger_summary.get('available', False))}",
                (
                    f"- last_status: {review_followup_ledger_summary.get('last_status', 'none')} | "
                    f"last_action={review_followup_ledger_summary.get('last_action', 'none')} | "
                    f"recent_entry_count={int(review_followup_ledger_summary.get('recent_entry_count', 0) or 0)}"
                ),
                (
                    f"- last_target: "
                    f"{dict(review_followup_ledger_summary.get('last_target_contract') or {}).get('symbol', 'n/a')} / "
                    f"{dict(review_followup_ledger_summary.get('last_target_contract') or {}).get('strategy_family', 'n/a')} | "
                    f"followup_command={review_followup_ledger_summary.get('last_followup_command', '') or 'none'}"
                ),
                f"- recent_status_counts: {dict(review_followup_ledger_summary.get('recent_status_counts') or {})}",
                f"- recent_action_counts: {list(review_followup_ledger_summary.get('recent_action_counts') or [])}",
                f"- summary: {review_followup_ledger_summary.get('summary', '')}",
                f"- ledger_path: {review_followup_ledger_summary.get('ledger_path', '')}",
                "",
            ]

        thesis_payload = dict(strategy_v2_thesis_validation or {})
        thesis_metrics = dict(thesis_payload.get("thesis_metrics") or {})
        thesis_before = dict(thesis_metrics.get("before_dedupe") or {})
        thesis_after = dict(thesis_metrics.get("after_dedupe") or {})
        thesis_comparison = dict(thesis_payload.get("comparison") or {})
        thesis_recommendation = dict(thesis_payload.get("deployment_recommendation") or {})
        thesis_lines: list[str] = []
        if thesis_payload:
            thesis_lines = [
                "## Thesis Dedupe Comparison",
                f"- available: {bool(thesis_payload.get('available', False))}",
                f"- comparison_axis: {thesis_payload.get('comparison_axis', 'thesis_dedupe')}",
                f"- evaluation_scope: {thesis_payload.get('evaluation_scope', 'portfolio_global')}",
                f"- blocked_duplicate_trades: {int((thesis_payload.get('sample_counts') or {}).get('blocked_duplicate_trades', 0))}",
                f"- blocked_active_cluster_cap_trades: {int((thesis_payload.get('sample_counts') or {}).get('blocked_active_cluster_cap_trades', 0))}",
                f"- keep_dedupe_enabled: {thesis_recommendation.get('keep_dedupe_enabled', True)}",
                f"- recommendation_reason: {thesis_recommendation.get('reason', 'not_available')}",
                (
                    f"- before_dedupe: trades={int(thesis_before.get('trades', 0))}, ev={float(thesis_before.get('ev', 0.0)):.4f}, "
                    f"p5={float(thesis_before.get('p5_ev', 0.0)):.4f}, max_dd={float(thesis_before.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(thesis_before.get('ulcer_index', 0.0)):.4f}"
                ),
                (
                    f"- after_dedupe: trades={int(thesis_after.get('trades', 0))}, ev={float(thesis_after.get('ev', 0.0)):.4f}, "
                    f"p5={float(thesis_after.get('p5_ev', 0.0)):.4f}, max_dd={float(thesis_after.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(thesis_after.get('ulcer_index', 0.0)):.4f}"
                ),
                (
                    f"- delta(after - before): ev={float(thesis_comparison.get('ev', 0.0)):.4f}, "
                    f"p5={float(thesis_comparison.get('p5_ev', 0.0)):.4f}, max_dd={float(thesis_comparison.get('max_drawdown', 0.0)):.4f}, "
                    f"ulcer={float(thesis_comparison.get('ulcer_index', 0.0)):.4f}"
                ),
                "",
            ]

        deployment_approval_lines: list[str] = []
        if deployment_approval_template:
            deployment_approval_lines = [
                "## Deployment Approval Template",
                f"- topline_status: {deployment_approval_template.get('topline_status', 'NOT_AVAILABLE')}",
                f"- topline_code: {deployment_approval_template.get('topline_code', 'approval_template_unavailable')}",
                f"- topline_message: {deployment_approval_template.get('topline_message', 'APPROVAL TEMPLATE NOT AVAILABLE.')}",
                f"- topline_summary_line: {deployment_approval_template.get('topline_summary_line', '')}",
                f"- playbook_go_no_go: {deployment_approval_template.get('playbook_go_no_go', 'NO_GO')}",
                f"- playbook_code: {deployment_approval_template.get('playbook_code', 'no_go_approval_template_unavailable')}",
                f"- playbook_action: {deployment_approval_template.get('playbook_action', 'block_rollout_until_template_available')}",
                f"- playbook_message: {deployment_approval_template.get('playbook_message', 'NO-GO: approval template is unavailable. Do not proceed until validation summary is generated.')}",
                f"- template_status: {deployment_approval_template.get('template_status', 'NOT_AVAILABLE')}",
                f"- template_reason: {deployment_approval_template.get('template_reason', 'approval_cross_display_unavailable')}",
                f"- threshold_lineage_winner_source: {deployment_approval_template.get('threshold_lineage_winner_source', 'unknown')}",
                (
                    f"- threshold_lineage_winner_selection_rule: "
                    f"{deployment_approval_template.get('threshold_lineage_winner_selection_rule', '')}"
                ),
                f"- threshold_lineage_winner_type: {deployment_approval_template.get('threshold_lineage_winner_type', 'unresolved')}",
                f"- threshold_lineage_audit_status: {deployment_approval_template.get('threshold_lineage_audit_status', 'not_available')}",
                f"- replay_derived_worst_scenario: {deployment_approval_template.get('replay_derived_worst_scenario', 'stressed_cost')}",
                (
                    f"- replay_derived_worst_scenario_source: "
                    f"{deployment_approval_template.get('replay_derived_worst_scenario_source', 'stressed_cost')}"
                ),
                (
                    f"- replay_derived_worst_scenario_status: "
                    f"{deployment_approval_template.get('replay_derived_worst_scenario_status', 'NOT_AVAILABLE')}"
                ),
                (
                    f"- replay_derived_worst_scenario_reason: "
                    f"{deployment_approval_template.get('replay_derived_worst_scenario_reason', 'not_available')}"
                ),
                (
                    f"- replay_derived_worst_scenario_divergence_status: "
                    f"{deployment_approval_template.get('replay_derived_worst_scenario_divergence_status', 'NOT_AVAILABLE')}"
                ),
                f"- replay_output_compared_scenarios: {deployment_approval_template.get('replay_output_compared_scenarios', [])}",
                f"- replay_output_input_trade_rows: {int(deployment_approval_template.get('replay_output_input_trade_rows', 0) or 0)}",
                f"- approval_warning_locked: {bool(deployment_approval_template.get('approval_warning_locked', False))}",
                f"- approval_warning_code: {deployment_approval_template.get('approval_warning_code', 'none')}",
                f"- approval_warning_message: {deployment_approval_template.get('approval_warning_message', 'approval_template_cross_display_is_consistent')}",
                (
                    f"- true_runner_promotion_action: "
                    f"{deployment_approval_template.get('true_runner_promotion_action', 'keep_current_path')}"
                ),
                "",
            ]
        approval_strip_summary = self._approval_strip_summary(
            deployment_approval_template=deployment_approval_template,
            operator_action_priority_summary=operator_action_priority_payload,
        )
        approval_strip_lines: list[str] = []
        if approval_strip_summary:
            approval_strip_lines = [
                "## Approval Strip",
                (
                    f"- approve={approval_strip_summary.get('approve_value', 'n/a')} | "
                    f"align={approval_strip_summary.get('align_value', 'n/a')} | "
                    f"act={approval_strip_summary.get('act_value', 'n/a')} | "
                    f"priority={approval_strip_summary.get('act_priority_level', 'monitor')}"
                ),
                f"- approve_reason: {approval_strip_summary.get('approve_reason', '')}",
                f"- align_reason: {approval_strip_summary.get('align_reason', '')}",
                f"- act_reason: {approval_strip_summary.get('act_reason', '')}",
                "",
            ]

        content = [
            f"# Validation Report: {symbol}",
            "",
            f"- generated_at_utc: {now.isoformat()}",
            f"- strategy_version: {version}",
            f"- status: **{status}**",
            "",
            "## Inputs",
            f"- walk_forward: train={self.settings.validation_wf_train_months}m, test={self.settings.validation_wf_test_months}m",
            f"- monte_carlo_simulations: {self.settings.validation_mc_simulations}",
            "",
            "## Strategy Metrics",
            f"- win_rate: {metric.get('win_rate', 0.0):.4f}",
            f"- avg_win: {metric.get('avg_win', 0.0):.4f}",
            f"- avg_loss: {metric.get('avg_loss', 0.0):.4f}",
            f"- EV: {metric.get('ev', 0.0):.4f}",
            f"- P1R/P2R/P3R: {metric.get('p1r', 0.0):.4f}/{metric.get('p2r', 0.0):.4f}/{metric.get('p3r', 0.0):.4f}",
            "",
            "## Walk-Forward",
            f"- trades: {wf.get('trades', 0)}",
            f"- mean_ev: {wf.get('mean_ev', 0.0):.4f}",
            f"- p5/p50/p95: {wf.get('p5_ev', 0.0):.4f}/{wf.get('p50_ev', 0.0):.4f}/{wf.get('p95_ev', 0.0):.4f}",
            "",
            "## Monte Carlo",
            f"- trades: {mc.get('trades', 0)}",
            f"- mean_ev: {mc.get('mean_ev', 0.0):.4f}",
            f"- p5/p50/p95: {mc.get('p5_ev', 0.0):.4f}/{mc.get('p50_ev', 0.0):.4f}/{mc.get('p95_ev', 0.0):.4f}",
            "",
            "## Approval Gates",
            f"- gate_1_wf_mean_ev_positive: {'PASS' if wf.get('mean_ev', 0.0) > 0 else 'FAIL'}",
            f"- gate_2_wf_p5_above_-0.8: {'PASS' if wf.get('p5_ev', -99.0) > -0.8 else 'FAIL'}",
            f"- gate_3_mc_p5_above_-0.6: {'PASS' if mc.get('p5_ev', -99.0) > -0.6 else 'FAIL'}",
            f"- gate_4_metric_ev_positive: {'PASS' if metric.get('ev', -99.0) > 0 else 'FAIL'}",
            "",
            *deployment_approval_lines,
            *approval_strip_lines,
            *eq_lines,
            *execution_friction_measurement_lines,
            *fi_lines,
            *fc_lines,
            *v2_lines,
            *forward_stress_regime_validation_lines,
            *kill_condition_automation_lines,
            *multi_strategy_ab_lines,
            *b_continuation_activation_lines,
            *b_continuation_edge_validation_lines,
            *strategy_cluster_balance_lines,
            *performance_decomposition_lines,
            *scalp_lines,
            *alpha_research_lines,
            *score_to_outcome_lines,
            *money_funnel_lines,
            *execution_degradation_lines,
            *family_execution_degradation_lines,
            *mode_advisory_lines,
            *operator_action_priority_lines,
            *outcome_control_trace_lines,
            *outcome_attribution_lines,
            *edge_experiment_lines,
            *edge_evolution_lines,
            *review_followup_ledger_lines,
            *rollout_recommendation_lines,
            *strategy_lifecycle_lines,
            *a_strategy_post_cost_edge_validation_lines,
            *promotion_governance_lines,
            *promotion_review_queue_lines,
            *promotion_remediation_queue_lines,
            *promotion_clearance_tracker_lines,
            *promotion_reopen_queue_lines,
            *promotion_decision_brief_lines,
            *auto_promotion_rollout_execution_lines,
            *promotion_lifecycle_history_lines,
            *research_promotion_operating_loop_lines,
            *positive_evidence_expansion_lines,
            *outcome_bucket_granularity_lines,
            *opportunity_capture_lines,
            *capital_allocator_lines,
            *lock_lines,
            *pbo_dsr_trial_writer_lines,
            *pbo_dsr_threshold_runner_lines,
            *artifact_store_lines,
            *pbo_dsr_lines,
            *pbo_dsr_metrics_lines,
            *stress_lines,
            *stress_replay_lineage_lines,
            *stress_replay_lines,
            *stress_replay_runner_lines,
            *stress_replay_writer_lines,
            *stress_replay_prototype_worker_lines,
            *thesis_lines,
            "## Notes",
            "- This report is generated from historical outcome logs and must be interpreted with live slippage/latency constraints.",
            "- Always re-run after major parameter or execution-policy changes.",
            "",
        ]
        file_path.write_text("\n".join(content), encoding="utf-8")

        return {
            "status": status,
            "path": str(file_path),
            "generated_at": now.isoformat(),
            "deployment_approval_summary": deployment_approval_template,
            "approval_strip_summary": approval_strip_summary,
            "execution_quality_summary": {
                "target_exit_ratio": float((execution_quality or {}).get("target_exit_ratio", 0.0)),
                "forced_exit_ratio": float((execution_quality or {}).get("forced_exit_ratio", 0.0)),
                "information_failure_ratio": float((execution_quality or {}).get("information_failure_ratio", 0.0)),
                "time_failure_ratio": float((execution_quality or {}).get("time_failure_ratio", 0.0)),
                "top_final_exit_reasons": [
                    {"reason": reason, "count": int(count)} for reason, count in eq_top_reasons
                ],
            }
            if execution_quality
            else None,
            "execution_friction_measurement_available": bool(
                execution_friction_measurement_payload.get("available", False)
            )
            if execution_friction_measurement_payload
            else False,
            "execution_friction_measurement_summary": (
                execution_friction_measurement_payload if execution_friction_measurement_payload else None
            ),
            "forward_stress_regime_validation_available": bool(
                forward_stress_regime_validation_payload.get("available", False)
            )
            if forward_stress_regime_validation_payload
            else False,
            "forward_stress_regime_validation_summary": (
                forward_stress_regime_validation_payload if forward_stress_regime_validation_payload else None
            ),
            "kill_condition_automation_available": bool(
                kill_condition_automation_payload.get("available", False)
            )
            if kill_condition_automation_payload
            else False,
            "kill_condition_automation_summary": (
                kill_condition_automation_payload if kill_condition_automation_payload else None
            ),
            "feature_importance_available": fi_available,
            "feature_importance_top": fi_ranking,
            "feature_calibration_available": fc_available,
            "feature_calibration_top": fc_top_adjustments,
            "strategy_v2_validation_available": bool(v2_payload.get("available", False)),
            "strategy_v2_validation_summary": {
                "preferred_live_mode": v2_recommendation.get("preferred_live_mode", "A_ONLY"),
                "recommendation_reason": v2_recommendation.get("reason", "not_available"),
                "eligible_closed_trades": int((v2_payload.get("sample_counts") or {}).get("eligible_closed_trades", 0)),
                "incremental_b_trades": int((v2_payload.get("sample_counts") or {}).get("incremental_b_trades", 0)),
                "best_ev_family": dict(family_summary.get("best_ev_family") or {}).get("name"),
                "best_ev_regime": dict(regime_summary.get("best_ev_regime") or {}).get("name"),
                "best_ev_session": dict(session_summary.get("best_ev_session") or {}).get("name"),
                "delta_ev_a_plus_b_minus_a_only": float(v2_comparison.get("ev", 0.0)),
                "delta_max_drawdown_a_plus_b_minus_a_only": float(v2_comparison.get("max_drawdown", 0.0)),
            }
            if v2_payload
            else None,
            "performance_decomposition_summary": performance_decomposition_summary,
            "score_to_outcome_funnel": score_to_outcome_payload if score_to_outcome_payload else None,
            "score_to_outcome_funnel_summary": {
                "available": bool(score_to_outcome_payload.get("available", False)),
                "reason": score_to_outcome_payload.get("reason", "not_available"),
                "report_window_days": int(score_to_outcome_payload.get("report_window_days", 0) or 0),
                "snapshot_selection": score_to_outcome_snapshot,
                "historical_execution_outcomes": score_to_outcome_history,
                "decomposition": score_to_outcome_decomposition,
                "runtime_candidates": int(score_to_outcome_snapshot.get("runtime_candidates", 0) or 0),
                "accepted_candidates": int(score_to_outcome_snapshot.get("accepted_candidates", 0) or 0),
                "blocked_candidates": int(score_to_outcome_snapshot.get("blocked_candidates", 0) or 0),
                "accept_rate": float(score_to_outcome_snapshot.get("accept_rate", 0.0) or 0.0),
                "submitted": int(score_to_outcome_history.get("submitted", 0) or 0),
                "filled": int(score_to_outcome_history.get("filled", 0) or 0),
                "closed": int(score_to_outcome_history.get("closed", 0) or 0),
                "profitable": int(score_to_outcome_history.get("profitable", 0) or 0),
                "baseline_cost_profitable": int(score_to_outcome_history.get("baseline_cost_profitable", 0) or 0),
                "fill_rate_from_submitted": float(score_to_outcome_history.get("fill_rate_from_submitted", 0.0) or 0.0),
                "close_rate_from_filled": float(score_to_outcome_history.get("close_rate_from_filled", 0.0) or 0.0),
                "profitable_rate_from_closed": float(score_to_outcome_history.get("profitable_rate_from_closed", 0.0) or 0.0),
                "baseline_cost_profitable_rate_from_closed": float(
                    score_to_outcome_history.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0
                ),
                "coverage_note": score_to_outcome_payload.get("coverage_note"),
                "money_funnel": money_funnel_payload if money_funnel_payload else None,
                "operating_kpis": build_outcome_funnel_operating_kpis(score_to_outcome_payload),
                "top_family_bucket": dict((list(score_to_outcome_decomposition.get("family") or [])[:1] or [{}])[0]),
                "top_regime_bucket": dict((list(score_to_outcome_decomposition.get("regime") or [])[:1] or [{}])[0]),
                "top_session_bucket": dict((list(score_to_outcome_decomposition.get("session") or [])[:1] or [{}])[0]),
                "top_entry_model_bucket": dict((list(score_to_outcome_decomposition.get("entry_model") or [])[:1] or [{}])[0]),
                "top_entry_timing_bucket": dict(
                    (list(score_to_outcome_decomposition.get("entry_timing_variant") or [])[:1] or [{}])[0]
                ),
                "top_execution_mode_bucket": dict(
                    (list(score_to_outcome_decomposition.get("execution_mode") or [])[:1] or [{}])[0]
                ),
                "top_execution_style_bucket": dict(
                    (list(score_to_outcome_decomposition.get("execution_style") or [])[:1] or [{}])[0]
                ),
            }
            if score_to_outcome_payload
            else None,
            "execution_degradation_advisory_available": bool(execution_degradation_payload.get("available", False)),
            "execution_degradation_advisory_summary": {
                "status": execution_degradation_payload.get("status", "healthy"),
                "healthy": bool(execution_degradation_payload.get("healthy", True)),
                "summary": execution_degradation_payload.get("summary", ""),
                "recommended_action": execution_degradation_payload.get("recommended_action", "continue_runtime_monitoring"),
                "reason_codes": list(execution_degradation_payload.get("reason_codes") or []),
                "sample_context": dict(execution_degradation_payload.get("sample_context") or {}),
                "top_reason": dict((execution_degradation_reasons[:1] or [{}])[0]),
            }
            if execution_degradation_payload
            else None,
            "family_execution_degradation_advisory": (
                family_execution_degradation_payload if family_execution_degradation_payload else None
            ),
            "family_execution_degradation_advisory_summary": {
                "available": bool(family_execution_degradation_payload.get("available", False)),
                "coverage_note": family_execution_degradation_payload.get("coverage_note", ""),
                "family_count": len(family_execution_degradation_rows),
                "top_family": dict((family_execution_degradation_rows[:1] or [{}])[0]),
            }
            if family_execution_degradation_payload
            else None,
            "mode_advisory": mode_advisory_payload if mode_advisory_payload else None,
            "mode_advisory_summary": {
                "available": bool(mode_advisory_payload.get("available", False)),
                "family_top": dict((list(mode_advisory_payload.get("family") or [])[:1] or [{}])[0]),
                "regime_top": dict((list(mode_advisory_payload.get("regime") or [])[:1] or [{}])[0]),
                "session_top": dict((list(mode_advisory_payload.get("session") or [])[:1] or [{}])[0]),
            }
            if mode_advisory_payload
            else None,
            "operator_action_priority": (
                operator_action_priority_payload if operator_action_priority_payload else None
            ),
            "operator_action_priority_summary": {
                "available": bool(operator_action_priority_payload.get("available", False)),
                "top_action": operator_action_priority_payload.get("top_action", "continue_runtime_monitoring"),
                "top_reason": operator_action_priority_payload.get("top_reason", ""),
                "top_action_followup_command": operator_action_priority_payload.get("top_action_followup_command", ""),
                "priority_level": operator_action_priority_payload.get("priority_level", "monitor"),
                "priority_source": operator_action_priority_payload.get("priority_source", "monitor"),
                "action_family": operator_action_priority_payload.get("action_family", "monitor"),
                "supporting_signals": list(operator_action_priority_payload.get("supporting_signals") or []),
                "blocking_signals": list(operator_action_priority_payload.get("blocking_signals") or []),
                "next_actions": [dict(item) for item in list(operator_action_priority_payload.get("next_actions") or [])[:3]],
                "capture_context": dict(operator_action_priority_payload.get("capture_context") or {}),
                "experiment_context": dict(operator_action_priority_payload.get("experiment_context") or {}),
                "experiment_execution_policy": dict(
                    operator_action_priority_payload.get("experiment_execution_policy") or {}
                ),
                "deferred_experiment_actions": [
                    dict(item) for item in list(operator_action_priority_payload.get("deferred_experiment_actions") or [])[:3]
                ],
                "advisory_only": bool(operator_action_priority_payload.get("advisory_only", True)),
            }
            if operator_action_priority_payload
            else None,
            "outcome_control_trace_available": bool(outcome_control_trace_summary.get("available", False))
            if outcome_control_trace_summary
            else False,
            "outcome_control_trace_summary": outcome_control_trace_summary,
            "outcome_attribution_available": bool(outcome_attribution_summary.get("available", False))
            if outcome_attribution_summary
            else False,
            "outcome_attribution_summary": outcome_attribution_summary,
            "edge_experiment_review_available": bool(edge_experiment_summary.get("available", False))
            if edge_experiment_summary
            else False,
            "edge_experiment_review_summary": edge_experiment_summary,
            "edge_evolution_rule_available": bool(edge_evolution_summary.get("available", False))
            if edge_evolution_summary
            else False,
            "edge_evolution_rule_summary": edge_evolution_summary,
            "review_followup_ledger_available": bool(review_followup_ledger_summary.get("available", False))
            if review_followup_ledger_summary
            else False,
            "review_followup_ledger_summary": review_followup_ledger_summary,
            "rollout_recommendation": rollout_recommendation_payload if rollout_recommendation_payload else None,
            "rollout_recommendation_available": bool(rollout_recommendation_payload.get("available", False))
            if rollout_recommendation_payload
            else False,
            "rollout_recommendation_summary": rollout_recommendation_payload if rollout_recommendation_payload else None,
            "strategy_lifecycle_available": bool(strategy_lifecycle_payload.get("available", False))
            if strategy_lifecycle_payload
            else False,
            "strategy_lifecycle_summary": strategy_lifecycle_payload if strategy_lifecycle_payload else None,
            "promotion_governance_available": bool(promotion_governance_payload.get("available", False))
            if promotion_governance_payload
            else False,
            "promotion_governance_summary": promotion_governance_payload if promotion_governance_payload else None,
            "promotion_review_queue_available": bool(promotion_review_queue_payload.get("available", False))
            if promotion_review_queue_payload
            else False,
            "promotion_review_queue_summary": promotion_review_queue_payload if promotion_review_queue_payload else None,
            "promotion_remediation_queue_available": bool(promotion_remediation_queue_payload.get("available", False))
            if promotion_remediation_queue_payload
            else False,
            "promotion_remediation_queue_summary": (
                promotion_remediation_queue_payload if promotion_remediation_queue_payload else None
            ),
            "promotion_clearance_tracker_available": bool(promotion_clearance_tracker_payload.get("available", False))
            if promotion_clearance_tracker_payload
            else False,
            "promotion_clearance_tracker_summary": (
                promotion_clearance_tracker_payload if promotion_clearance_tracker_payload else None
            ),
            "promotion_reopen_queue_available": bool(promotion_reopen_queue_payload.get("available", False))
            if promotion_reopen_queue_payload
            else False,
            "promotion_reopen_queue_summary": promotion_reopen_queue_payload if promotion_reopen_queue_payload else None,
            "promotion_decision_brief_available": bool(promotion_decision_brief_payload.get("available", False))
            if promotion_decision_brief_payload
            else False,
            "promotion_decision_brief_summary": (
                promotion_decision_brief_payload if promotion_decision_brief_payload else None
            ),
            "auto_promotion_rollout_execution_available": bool(
                auto_promotion_rollout_execution_payload.get("available", False)
            )
            if auto_promotion_rollout_execution_payload
            else False,
            "auto_promotion_rollout_execution_summary": (
                auto_promotion_rollout_execution_payload if auto_promotion_rollout_execution_payload else None
            ),
            "promotion_lifecycle_history_available": bool(promotion_lifecycle_history_payload.get("available", False))
            if promotion_lifecycle_history_payload
            else False,
            "promotion_lifecycle_history_summary": (
                promotion_lifecycle_history_payload if promotion_lifecycle_history_payload else None
            ),
            "research_promotion_operating_loop_available": bool(
                research_promotion_operating_loop_payload.get("available", False)
            )
            if research_promotion_operating_loop_payload
            else False,
            "research_promotion_operating_loop_summary": (
                research_promotion_operating_loop_payload if research_promotion_operating_loop_payload else None
            ),
            "multi_strategy_ab_available": bool(multi_strategy_ab_payload.get("available", False))
            if multi_strategy_ab_payload
            else False,
            "multi_strategy_ab_summary": multi_strategy_ab_payload if multi_strategy_ab_payload else None,
            "b_continuation_activation_available": bool(
                b_continuation_activation_payload.get("available", False)
            )
            if b_continuation_activation_payload
            else False,
            "b_continuation_activation_summary": (
                b_continuation_activation_payload if b_continuation_activation_payload else None
            ),
            "b_continuation_edge_validation_available": bool(
                b_continuation_edge_validation_payload.get("available", False)
            )
            if b_continuation_edge_validation_payload
            else False,
            "b_continuation_edge_validation_summary": (
                b_continuation_edge_validation_payload if b_continuation_edge_validation_payload else None
            ),
            "strategy_cluster_balance_available": bool(
                strategy_cluster_balance_payload.get("available", False)
            )
            if strategy_cluster_balance_payload
            else False,
            "strategy_cluster_balance_summary": (
                strategy_cluster_balance_payload if strategy_cluster_balance_payload else None
            ),
            "a_strategy_post_cost_edge_validation_available": bool(
                a_strategy_post_cost_edge_validation_payload.get("available", False)
            )
            if a_strategy_post_cost_edge_validation_payload
            else False,
            "a_strategy_post_cost_edge_validation_summary": (
                a_strategy_post_cost_edge_validation_payload
                if a_strategy_post_cost_edge_validation_payload
                else None
            ),
            "positive_evidence_expansion_available": bool(positive_evidence_expansion_payload.get("available", False))
            if positive_evidence_expansion_payload
            else False,
            "positive_evidence_expansion_summary": (
                positive_evidence_expansion_payload if positive_evidence_expansion_payload else None
            ),
            "outcome_bucket_granularity_available": bool(outcome_bucket_granularity_payload.get("available", False))
            if outcome_bucket_granularity_payload
            else False,
            "outcome_bucket_granularity_summary": (
                outcome_bucket_granularity_payload if outcome_bucket_granularity_payload else None
            ),
            "opportunity_capture_available": bool(opportunity_capture_payload.get("available", False))
            if opportunity_capture_payload
            else False,
            "opportunity_capture_summary": opportunity_capture_payload if opportunity_capture_payload else None,
            "capital_allocator_available": bool(capital_allocator_payload.get("available", False))
            if capital_allocator_payload
            else False,
            "capital_allocator_summary": capital_allocator_payload if capital_allocator_payload else None,
            "strategy_v2_scalp_experiment_available": bool(scalp_payload.get("available", False)),
            "strategy_v2_scalp_experiment_summary": {
                "preferred_branch": scalp_comparison.get("preferred_branch", "none"),
                "recommendation_reason": scalp_comparison.get("recommendation_reason", "not_available"),
                "delta_top_expected_ev_at_size_r": float(scalp_comparison.get("delta_top_expected_ev_at_size_r", 0.0)),
                "delta_top_expected_win_prob": float(scalp_comparison.get("delta_top_expected_win_prob", 0.0)),
                "sample_counts": dict(scalp_payload.get("sample_counts") or {}),
            }
            if scalp_payload
            else None,
            "alpha_research_pipeline_available": bool(alpha_research_payload.get("available", False)),
            "alpha_research_pipeline_summary": {
                "alpha_research_candidate_count": int(alpha_research_summary.get("alpha_research_candidate_count", 0)),
                "focus_symbol_candidate_count": int(alpha_research_summary.get("focus_symbol_candidate_count", 0)),
                "top_reason": alpha_research_summary.get("top_reason"),
                "top_family": alpha_research_summary.get("top_family"),
                "top_regime": alpha_research_summary.get("top_regime"),
                "top_session": alpha_research_summary.get("top_session"),
                "avg_softened_risk_r": float(alpha_research_summary.get("avg_softened_risk_r", 0.0)),
                "analysis_symbol": alpha_research_payload.get("analysis_symbol"),
                "aligned_candidate_count": int(alpha_research_alignment.get("aligned_candidate_count", 0)),
                "top_alignment_focus": alpha_research_alignment.get("top_focus"),
                "top_alignment_bucket": alpha_research_alignment.get("top_bucket"),
                "recommended_action": alpha_research_action_summary.get("recommended_action"),
                "recommended_scope": alpha_research_action_summary.get("recommended_scope"),
                "recommended_reason": alpha_research_action_summary.get("recommended_reason"),
                "shadow_experiment_type": alpha_research_action_summary.get("shadow_experiment_type"),
                "recommended_focus": alpha_research_action_summary.get("focus"),
                "recommended_bucket": alpha_research_action_summary.get("bucket"),
                "confidence": alpha_research_action_summary.get("confidence"),
                "sample_note": alpha_research_action_summary.get("sample_note"),
                "recommended_action_deferred_by_sequence": bool(
                    alpha_research_action_summary.get("deferred_by_experiment_sequence", False)
                ),
                "recommended_action_current_priority_experiment": alpha_research_action_summary.get(
                    "current_priority_experiment"
                ),
                "recommended_action_current_priority_action": alpha_research_action_summary.get(
                    "current_priority_action"
                ),
                "top_shadow_experiment_id": alpha_research_top_experiment.get("experiment_id"),
                "top_shadow_experiment_title": alpha_research_top_experiment.get("title"),
                "top_shadow_experiment_target": alpha_research_top_experiment.get("target"),
                "top_shadow_experiment_objective": alpha_research_top_experiment.get("objective"),
                "top_shadow_experiment_confidence": alpha_research_top_experiment.get("confidence"),
                "top_shadow_experiment_observe_metrics": list(alpha_research_top_experiment.get("observe_metrics") or []),
                "top_shadow_experiment_success_criteria": list(alpha_research_top_experiment.get("success_criteria") or []),
                "top_shadow_experiment_stop_conditions": list(alpha_research_top_experiment.get("stop_conditions") or []),
                "top_shadow_experiment_deferred_by_sequence": bool(
                    alpha_research_top_experiment.get("deferred_by_experiment_sequence", False)
                ),
                "experiment_sequence_state": alpha_research_experiment_sequence.get("state"),
                "experiment_sequence_summary": alpha_research_experiment_sequence.get("summary"),
                "entry_timing_locked": bool(alpha_research_experiment_sequence.get("entry_timing_locked", False)),
                "execution_style_locked": bool(alpha_research_experiment_sequence.get("execution_style_locked", False)),
                "exit_optimization_allowed": bool(
                    alpha_research_experiment_sequence.get("exit_optimization_allowed", False)
                ),
                "current_priority_experiment": alpha_research_experiment_sequence.get("current_priority_experiment"),
                "current_priority_action": alpha_research_experiment_sequence.get("current_priority_action"),
                "shadow_experiment_template_count": len(alpha_research_experiment_templates),
                "evidence_available": bool(alpha_research_evidence_summary.get("available", False)),
                "evidence_top_reason": alpha_research_reason_summary.get("top_reason"),
                "evidence_focus_aligned_candidates": int(alpha_research_focus_summary.get("aligned_candidate_count", 0)),
                "evidence_top_focus": alpha_research_focus_summary.get("top_focus"),
                "evidence_top_bucket": alpha_research_focus_summary.get("top_bucket"),
                "evidence_top_family_bottleneck": dict(alpha_research_outcome_summary.get("top_family_bottleneck") or {}).get("key"),
                "evidence_top_regime_bottleneck": dict(alpha_research_outcome_summary.get("top_regime_bottleneck") or {}).get("key"),
                "evidence_top_session_bottleneck": dict(alpha_research_outcome_summary.get("top_session_bottleneck") or {}).get("key"),
                "false_negative_suspect_count": len(alpha_research_evidence_summary.get("false_negative_suspects") or []),
                "softening_review_available": bool(alpha_research_softening_review.get("available", False)),
                "softening_top_bucket": dict(alpha_research_softening_review.get("top_candidate") or {}).get("bucket"),
                "softening_top_priority": dict(alpha_research_softening_review.get("top_candidate") or {}).get("review_priority"),
                "softening_review_count": len(alpha_research_softening_review.get("review_items") or []),
                "promotion_watchlist_available": bool(alpha_research_promotion_watchlist.get("available", False)),
                "promotion_watchlist_count": int(alpha_research_promotion_watchlist.get("watchlist_count", 0) or 0),
                "promotion_top_bucket": dict((list(alpha_research_promotion_watchlist.get("watch_items") or [])[:1] or [{}])[0]).get("bucket"),
                "promotion_top_not_ready_reason": dict((list(alpha_research_promotion_watchlist.get("watch_items") or [])[:1] or [{}])[0]).get("not_ready_reason"),
                "improvement_priority": dict(edge_experiment_summary.get("operating_discipline") or {}).get(
                    "improvement_priority"
                )
                if edge_experiment_summary
                else None,
                "signal_density_control_review_allowed": bool(
                    dict(edge_experiment_summary.get("operating_discipline") or {}).get(
                        "signal_density_control_review_allowed", False
                    )
                )
                if edge_experiment_summary
                else False,
                "multi_strategy_expansion_review_allowed": bool(
                    dict(edge_experiment_summary.get("operating_discipline") or {}).get(
                        "multi_strategy_expansion_review_allowed", False
                    )
                )
                if edge_experiment_summary
                else False,
                "deferred_review_backlog": list(
                    dict(edge_experiment_summary.get("operating_discipline") or {}).get("deferred_review_backlog") or []
                )
                if edge_experiment_summary
                else [],
            }
            if alpha_research_payload
            else None,
            "strategy_v2_lock_validation_available": bool(lock_payload.get("available", False)),
            "strategy_v2_lock_validation_summary": {
                "keep_lock_enabled": bool(lock_recommendation.get("keep_lock_enabled", True)),
                "recommendation_reason": lock_recommendation.get("reason", "not_available"),
                "blocked_transition_trades": int((lock_payload.get("sample_counts") or {}).get("blocked_transition_trades", 0)),
                "blocked_shock_trades": int((lock_payload.get("sample_counts") or {}).get("blocked_shock_trades", 0)),
                "shock_clamped_trades": int((lock_payload.get("sample_counts") or {}).get("shock_clamped_trades", 0)),
                "delta_ev_after_minus_before": float(lock_comparison.get("ev", 0.0)),
                "delta_max_drawdown_after_minus_before": float(lock_comparison.get("max_drawdown", 0.0)),
            }
            if lock_payload
            else None,
            "strategy_v2_pbo_dsr_trial_writer_available": bool(pbo_dsr_trial_writer_payload.get("available", False)),
            "strategy_v2_pbo_dsr_trial_writer_summary": {
                "implementation_status": pbo_dsr_trial_writer_payload.get("implementation_status", "not_available"),
                "reason": pbo_dsr_trial_writer_payload.get("reason", "not_available"),
                "sample_counts": dict(pbo_dsr_trial_writer_payload.get("sample_counts") or {}),
                "selected_trial_run_id": pbo_dsr_trial_writer_payload.get("selected_trial_run_id"),
                "parameter_families_present": list(pbo_dsr_trial_writer_payload.get("parameter_families_present") or []),
            }
            if pbo_dsr_trial_writer_payload
            else None,
            "strategy_v2_pbo_dsr_threshold_runner_available": bool(pbo_dsr_threshold_runner_payload.get("available", False)),
            "strategy_v2_pbo_dsr_threshold_runner_summary": {
                "implementation_status": pbo_dsr_threshold_runner_payload.get("implementation_status", "not_available"),
                "reason": pbo_dsr_threshold_runner_payload.get("reason", "not_available"),
                "lineage_namespace": pbo_dsr_threshold_runner_payload.get("lineage_namespace", "not_available"),
                "selection_rule": pbo_dsr_threshold_runner_payload.get("selection_rule", "not_available"),
                "sample_counts": dict(pbo_dsr_threshold_runner_payload.get("sample_counts") or {}),
                "selected_trial_run_id": pbo_dsr_threshold_runner_payload.get("selected_trial_run_id"),
                "parameter_families_present": list(
                    pbo_dsr_threshold_runner_payload.get("parameter_families_present") or []
                ),
            }
            if pbo_dsr_threshold_runner_payload
            else None,
            "strategy_v2_pbo_dsr_artifact_store_ready": bool(artifact_store_payload.get("artifact_store_ready", False)),
            "strategy_v2_pbo_dsr_artifact_store_summary": {
                "available": bool(artifact_store_payload.get("available", False)),
                "metrics_available": bool(artifact_store_payload.get("metrics_available", False)),
                "implementation_status": artifact_store_payload.get("implementation_status", "not_available"),
                "reason": artifact_store_payload.get("reason", "not_available"),
                "counts": artifact_store_counts,
                "selection_rule_counts": artifact_store_selection_rule_counts,
                "selection_universe_summary": artifact_store_selection_universe_summary,
                "parameter_families_present": list(artifact_store_payload.get("parameter_families_present") or []),
            }
            if artifact_store_payload
            else None,
            "strategy_v2_pbo_dsr_design_ready": bool(pbo_dsr_payload.get("design_ready", False)),
            "strategy_v2_pbo_dsr_design_summary": {
                "available": bool(pbo_dsr_payload.get("available", False)),
                "implementation_status": pbo_dsr_payload.get("implementation_status", "not_available"),
                "reason": pbo_dsr_payload.get("reason", "not_available"),
                "blocked_by": list(pbo_dsr_payload.get("blocked_by") or []),
                "next_steps": list(pbo_dsr_payload.get("next_steps") or []),
            }
            if pbo_dsr_payload
            else None,
            "strategy_v2_pbo_dsr_metrics_available": bool(pbo_dsr_metrics_payload.get("available", False)),
            "strategy_v2_pbo_dsr_metrics_summary": {
                "metrics_complete": bool(pbo_dsr_metrics_payload.get("metrics_complete", False)),
                "reason": pbo_dsr_metrics_payload.get("reason", "not_available"),
                "pbo_value": dict(pbo_dsr_metrics_payload.get("pbo") or {}).get("value"),
                "pbo_status": dict(pbo_dsr_metrics_payload.get("pbo") or {}).get("status", "not_available"),
                "dsr_value": dict(pbo_dsr_metrics_payload.get("dsr") or {}).get("value"),
                "dsr_probability": dict(pbo_dsr_metrics_payload.get("dsr") or {}).get("probability"),
                "dsr_status": dict(pbo_dsr_metrics_payload.get("dsr") or {}).get("status", "not_available"),
                "selected_trial_writer_source": dict(pbo_dsr_metrics_payload.get("selected_trial") or {}).get(
                    "writer_source", "unknown"
                ),
                "lineage_audit_status": dict(pbo_dsr_metrics_payload.get("lineage_audit") or {}).get(
                    "audit_status", "not_available"
                ),
                "lineage_audit_reason": dict(pbo_dsr_metrics_payload.get("lineage_audit") or {}).get(
                    "reason", "not_available"
                ),
                "selected_trial_from_runtime_proxy": bool(
                    dict(pbo_dsr_metrics_payload.get("lineage_audit") or {}).get("selected_trial_from_runtime_proxy", False)
                ),
                "selected_trial_from_true_threshold": bool(
                    dict(pbo_dsr_metrics_payload.get("lineage_audit") or {}).get("selected_trial_from_true_threshold", False)
                ),
                "selection_universe_summary": dict(pbo_dsr_metrics_payload.get("selection_universe_summary") or {}),
                "decision": dict(pbo_dsr_metrics_payload.get("deployment_recommendation") or {}).get("decision", "not_ready"),
                "meets_protocol_gate": bool(
                    dict(pbo_dsr_metrics_payload.get("deployment_recommendation") or {}).get("meets_protocol_gate", False)
                ),
            }
            if pbo_dsr_metrics_payload
            else None,
            "strategy_v2_stress_validation_available": bool(stress_payload.get("available", False)),
            "strategy_v2_stress_validation_summary": {
                "stress_pass": bool(stress_recommendation.get("stress_pass", False)),
                "recommendation_reason": stress_recommendation.get("reason", "not_available"),
                "worst_scenario": stress_recommendation.get("worst_scenario", "stressed_cost"),
                "worst_scenario_source": stress_recommendation.get("worst_scenario_source", "stressed_cost"),
                "replay_gate_applied": bool(stress_recommendation.get("replay_gate_applied", False)),
                "replay_gate_reason": stress_recommendation.get("replay_gate_reason", "approximation_only"),
                "divergence_gate_applied": bool(stress_recommendation.get("divergence_gate_applied", False)),
                "divergence_problem_scenarios": list(stress_recommendation.get("divergence_problem_scenarios") or []),
                "worst_divergence_scenario": stress_recommendation.get("worst_divergence_scenario"),
                "execution_data_trades": int((stress_payload.get("sample_counts") or {}).get("execution_data_trades", 0)),
                "estimate_only_trades": int((stress_payload.get("sample_counts") or {}).get("estimate_only_trades", 0)),
                "latency_reference_trades": int((stress_payload.get("sample_counts") or {}).get("latency_reference_trades", 0)),
                "shock_regime_trades": int((stress_payload.get("sample_counts") or {}).get("shock_regime_trades", 0)),
                "delta_ev_stressed_minus_baseline": float(stress_comparison.get("ev", 0.0)),
                "delta_max_drawdown_stressed_minus_baseline": float(stress_comparison.get("max_drawdown", 0.0)),
                "scenario_statuses": stress_scenario_statuses,
                "replay_output_artifacts_available": bool(stress_replay_output_artifacts.get("available", False)),
                "replay_output_scenarios_compared": int(
                    (stress_replay_output_artifacts.get("summary_counts") or {}).get("scenarios_compared", 0)
                ),
                "replay_output_lineage_summary": dict(stress_replay_output_artifacts.get("lineage_summary") or {}),
            }
            if stress_payload
            else None,
            "strategy_v2_stress_replay_lineage_available": bool(stress_replay_lineage_payload.get("available", False)),
            "strategy_v2_stress_replay_lineage_summary": {
                "runtime_inputs_ready": bool(stress_replay_lineage_payload.get("runtime_inputs_ready", False)),
                "reason": stress_replay_lineage_payload.get("reason", "not_available"),
                "coverage": dict(stress_replay_lineage_payload.get("coverage") or {}),
                "gap_counts": dict(stress_replay_lineage_payload.get("gap_counts") or {}),
            }
            if stress_replay_lineage_payload
            else None,
            "strategy_v2_stress_replay_assessment_available": bool(stress_replay_payload.get("available", False)),
            "strategy_v2_stress_replay_assessment_summary": {
                "full_replay_ready": bool(stress_replay_payload.get("full_replay_ready", False)),
                "replacement_recommended": bool(stress_replay_payload.get("replacement_recommended", False)),
                "true_runner_ready": bool(dict(stress_replay_payload.get("true_runner_readiness") or {}).get("true_runner_ready", False)),
                "true_runner_stage": dict(stress_replay_payload.get("true_runner_readiness") or {}).get("stage", "prototype_only"),
                "decision": stress_replay_recommendation.get("decision", "keep_approximation"),
                "priority": stress_replay_recommendation.get("priority", "low"),
                "reason": stress_replay_recommendation.get("reason", "not_available"),
                "true_runner_promotion_ready": bool(stress_replay_recommendation.get("true_runner_promotion_ready", False)),
                "true_runner_promotion_status": stress_replay_recommendation.get(
                    "true_runner_promotion_status", "NOT_APPLICABLE"
                ),
                "true_runner_promotion_action": stress_replay_recommendation.get(
                    "true_runner_promotion_action", "keep_current_path"
                ),
                "threshold_lineage_audit_status": stress_replay_recommendation.get(
                    "threshold_lineage_audit_status", "not_available"
                ),
                "replay_output_lineage_alignment_status": stress_replay_recommendation.get(
                    "replay_output_lineage_alignment_status", "NOT_AVAILABLE"
                ),
                "replay_output_lineage_alignment_reason": stress_replay_recommendation.get(
                    "replay_output_lineage_alignment_reason", "not_available"
                ),
                "replay_output_lineage_compared_scenarios": list(
                    stress_replay_recommendation.get("replay_output_lineage_compared_scenarios") or []
                ),
                "replay_output_lineage_input_trade_rows": int(
                    stress_replay_recommendation.get("replay_output_lineage_input_trade_rows", 0) or 0
                ),
                "selected_trial_writer_source": stress_replay_recommendation.get(
                    "selected_trial_writer_source", "unknown"
                ),
                "approval_cross_display": dict(stress_replay_recommendation.get("approval_cross_display") or {}),
                "coverage": dict(stress_replay_payload.get("coverage") or {}),
                "worst_scenario": dict(stress_replay_payload.get("scenario_evidence") or {}).get("worst_scenario", "stressed_cost"),
            }
            if stress_replay_payload
            else None,
            "strategy_v2_stress_replay_runner_contract_available": bool(stress_replay_runner_payload.get("available", False)),
            "strategy_v2_stress_replay_runner_contract_summary": {
                "runtime_job_ready": bool(stress_replay_runner_payload.get("runtime_job_ready", False)),
                "true_runner_ready": bool(dict(stress_replay_runner_payload.get("true_runner_readiness") or {}).get("true_runner_ready", False)),
                "true_runner_stage": dict(stress_replay_runner_payload.get("true_runner_readiness") or {}).get("stage", "prototype_only"),
                "implementation_status": stress_replay_runner_payload.get("implementation_status", "not_available"),
                "reason": stress_replay_runner_payload.get("reason", "not_available"),
                "readiness": dict(stress_replay_runner_payload.get("readiness") or {}),
            }
            if stress_replay_runner_payload
            else None,
            "strategy_v2_stress_replay_lineage_writer_available": bool(stress_replay_writer_payload.get("available", False)),
            "strategy_v2_stress_replay_lineage_writer_summary": {
                "artifacts_written": bool(stress_replay_writer_payload.get("artifacts_written", False)),
                "runtime_job_ready": bool(stress_replay_writer_payload.get("runtime_job_ready", False)),
                "implementation_status": stress_replay_writer_payload.get("implementation_status", "not_available"),
                "reason": stress_replay_writer_payload.get("reason", "not_available"),
                "sample_counts": dict(stress_replay_writer_payload.get("sample_counts") or {}),
            }
            if stress_replay_writer_payload
            else None,
            "strategy_v2_stress_replay_prototype_worker_available": bool(
                stress_replay_prototype_worker_payload.get("available", False)
            ),
            "strategy_v2_stress_replay_prototype_worker_summary": {
                "executed": bool(stress_replay_prototype_worker_payload.get("executed", False)),
                "runtime_job_ready": bool(stress_replay_prototype_worker_payload.get("runtime_job_ready", False)),
                "reason": stress_replay_prototype_worker_payload.get("reason", "not_available"),
                "sample_counts": dict(stress_replay_prototype_worker_payload.get("sample_counts") or {}),
            }
            if stress_replay_prototype_worker_payload
            else None,
            "strategy_v2_thesis_validation_available": bool(thesis_payload.get("available", False)),
            "strategy_v2_thesis_validation_summary": {
                "keep_dedupe_enabled": bool(thesis_recommendation.get("keep_dedupe_enabled", True)),
                "recommendation_reason": thesis_recommendation.get("reason", "not_available"),
                "blocked_duplicate_trades": int((thesis_payload.get("sample_counts") or {}).get("blocked_duplicate_trades", 0)),
                "blocked_active_cluster_cap_trades": int(
                    (thesis_payload.get("sample_counts") or {}).get("blocked_active_cluster_cap_trades", 0)
                ),
                "delta_ev_after_minus_before": float(thesis_comparison.get("ev", 0.0)),
                "delta_max_drawdown_after_minus_before": float(thesis_comparison.get("max_drawdown", 0.0)),
            }
            if thesis_payload
            else None,
        }
