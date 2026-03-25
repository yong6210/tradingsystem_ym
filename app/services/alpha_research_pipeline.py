from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.services.edge_experiment_review import build_edge_experiment_review, summarize_edge_experiment_review

_SOFTENING_RESEARCH_REASONS = {
    "risk_budget_below_min",
    "adjusted_score_non_positive",
}
_EXIT_SHADOW_REVIEW_ACTIONS = {
    "run_shadow_exit_review",
    "run_shadow_exit_timing_review",
}


class AlphaResearchPipelineService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @staticmethod
    def _dedupe_strings(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    @staticmethod
    def _session_state(row: dict[str, Any]) -> str:
        return str(((row.get("session_guidance") or {}).get("state")) or "unknown")

    @staticmethod
    def _experiment_sequence(score_to_outcome_funnel: dict[str, Any] | None) -> dict[str, Any] | None:
        edge_review = build_edge_experiment_review(score_to_outcome_funnel=score_to_outcome_funnel)
        edge_summary = summarize_edge_experiment_review(edge_review)
        if not edge_summary:
            return None
        return dict(edge_summary.get("experiment_sequence") or {})

    @staticmethod
    def _annotate_with_experiment_sequence(
        payload: dict[str, Any] | None,
        *,
        experiment_sequence: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        source = dict(payload or {})
        sequence = dict(experiment_sequence or {})
        if not source:
            return None
        if not sequence:
            return source

        recommended_action = str(source.get("recommended_action") or "")
        deferred = recommended_action in _EXIT_SHADOW_REVIEW_ACTIONS and not bool(
            sequence.get("exit_optimization_allowed", False)
        )
        source.update(
            {
                "experiment_sequence_state": str(sequence.get("state") or "unknown"),
                "current_priority_experiment": str(sequence.get("current_priority_experiment") or "unknown"),
                "current_priority_action": str(sequence.get("current_priority_action") or "unknown"),
                "exit_optimization_allowed": bool(sequence.get("exit_optimization_allowed", False)),
                "deferred_by_experiment_sequence": deferred,
                "sequencing_reason": str(sequence.get("summary") or ""),
            }
        )
        return source

    @classmethod
    def _sequencing_next_steps(cls, experiment_sequence: dict[str, Any] | None) -> list[str]:
        sequence = dict(experiment_sequence or {})
        if not sequence:
            return []

        state = str(sequence.get("state") or "")
        if state == "entry_timing_first":
            return [
                "lock entry timing first by comparing early_limit versus reaction_confirmed before execution-style or exit review",
                "keep execution style on the current baseline until the entry-timing comparison is decision-ready",
                "defer exit optimization review until both split baselines are locked and at least 8 closes are available",
            ]
        if state == "execution_style_second":
            return [
                "entry timing is already locked; compare passive_limit versus market next before exit review",
                "keep exit optimization deferred until execution style is also locked",
            ]
        if state == "sample_building_before_exit_optimization":
            return [
                "entry timing and execution style both have directional coverage; accumulate more closed trades before exit review",
                "do not couple exit optimization to the current split cycle until the exit-review floor is reached",
            ]
        if state == "exit_optimization_allowed":
            return [
                "entry timing and execution style are locked; exit optimization review can run next without changing hard gates",
            ]
        return []

    @staticmethod
    def _focus_axis(focus_name: str) -> str:
        if focus_name.startswith("family_"):
            return "family"
        if focus_name.startswith("regime_"):
            return "regime"
        if focus_name.startswith("session_"):
            return "session"
        if focus_name.startswith("entry_model_"):
            return "entry_model"
        return "global"

    @staticmethod
    def _candidate_sort_key(row: dict[str, Any]) -> tuple[float, float, float, float, str]:
        return (
            float(row.get("research_focus_match_count", 0) or 0.0),
            float(row.get("expected_ev_at_recommended_size_r", row.get("expected_ev_r", 0.0)) or 0.0),
            float(row.get("alpha_research_softened_risk_r", 0.0) or 0.0),
            -float(row.get("alpha_research_gap", 0.0) or 0.0),
            str(row.get("symbol") or ""),
        )

    @staticmethod
    def _top_key(counter: Counter[str]) -> str | None:
        if not counter:
            return None
        return max(counter.items(), key=lambda item: (item[1], item[0]))[0]

    @staticmethod
    def _avg(values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 4)

    @classmethod
    def _focus_matches(
        cls,
        *,
        row: dict[str, Any],
        tuning_focus: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        family = str(row.get("strategy_family") or "unknown")
        regime = str(row.get("regime") or "unknown")
        session = cls._session_state(row)
        entry_model = str(row.get("entry_model") or "unknown").upper()
        matches: list[dict[str, Any]] = []
        for focus in tuning_focus:
            focus_name = str(focus.get("focus") or "")
            bucket = str(focus.get("bucket") or "")
            if not focus_name or not bucket:
                continue
            matched = False
            if focus_name.startswith("family_") and family == bucket:
                matched = True
            elif focus_name.startswith("regime_") and regime == bucket:
                matched = True
            elif focus_name.startswith("session_") and session == bucket:
                matched = True
            elif focus_name.startswith("entry_model_") and entry_model == bucket.upper():
                matched = True
            if not matched:
                continue
            matches.append(
                {
                    "focus": focus_name,
                    "bucket": bucket,
                    "metric": str(focus.get("metric") or ""),
                    "value": round(float(focus.get("value", 0.0) or 0.0), 4),
                }
            )
        return matches

    @classmethod
    def _research_focus_alignment(
        cls,
        *,
        rows: list[dict[str, Any]],
        analysis_symbol: str | None,
        performance_decomposition_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        tuning_focus = list((performance_decomposition_summary or {}).get("tuning_focus") or [])
        if not tuning_focus:
            return None

        focus_items: list[dict[str, Any]] = []
        for focus in tuning_focus:
            focus_name = str(focus.get("focus") or "")
            bucket = str(focus.get("bucket") or "")
            samples = int(focus.get("samples", 0) or 0)
            matched_rows = [
                row
                for row in rows
                if any(
                    str(match.get("focus") or "") == focus_name and str(match.get("bucket") or "") == bucket
                    for match in list(row.get("research_focus_matches") or [])
                )
            ]
            reason_counts = Counter(
                str(row.get("alpha_research_reason") or row.get("block_reason") or "unknown") for row in matched_rows
            )
            focus_items.append(
                {
                    "focus": focus_name,
                    "bucket": bucket,
                    "metric": str(focus.get("metric") or ""),
                    "value": round(float(focus.get("value", 0.0) or 0.0), 4),
                    "samples": samples,
                    "candidates": len(matched_rows),
                    "top_reason": cls._top_key(reason_counts),
                    "top_symbol": cls._top_key(Counter(str(row.get("symbol") or "") for row in matched_rows)),
                }
            )
        focus_items.sort(
            key=lambda item: (
                -int(item.get("candidates", 0)),
                -abs(float(item.get("value", 0.0) or 0.0)),
                str(item.get("focus") or ""),
                str(item.get("bucket") or ""),
            )
        )
        aligned_candidate_count = sum(1 for row in rows if int(row.get("research_focus_match_count", 0) or 0) > 0)
        top_item = dict(focus_items[0]) if focus_items else {}
        return {
            "available": True,
            "analysis_symbol": analysis_symbol,
            "aligned_candidate_count": aligned_candidate_count,
            "top_focus": top_item.get("focus"),
            "top_bucket": top_item.get("bucket"),
            "focus_items": focus_items,
        }

    @staticmethod
    def _confidence(samples: int) -> str:
        if samples >= 8:
            return "high"
        if samples >= 4:
            return "medium"
        return "low"

    @classmethod
    def _sample_note(cls, samples: int) -> str:
        confidence = cls._confidence(samples)
        if confidence == "high":
            return "repeat evidence is present"
        if confidence == "medium":
            return "usable evidence, but still limited"
        return "sample is thin; treat as research hint only"

    @classmethod
    def _recommended_action(cls, focus: dict[str, Any]) -> dict[str, Any]:
        focus_name = str(focus.get("focus") or "")
        bucket = str(focus.get("bucket") or "")
        metric = str(focus.get("metric") or "")
        value = round(float(focus.get("value", 0.0) or 0.0), 4)
        samples = int(focus.get("samples", 0) or 0)
        aligned_candidates = int(focus.get("candidates", 0) or 0)
        confidence = cls._confidence(samples)

        action = {
            "focus": focus_name,
            "bucket": bucket,
            "metric": metric,
            "value": value,
            "samples": samples,
            "aligned_candidates": aligned_candidates,
            "recommended_action": "run_shadow_quality_review",
            "recommended_scope": "global",
            "recommended_reason": "quality decomposition surfaced a research focus that needs shadow review",
            "shadow_experiment_type": "quality_focus_review",
            "target_family": None,
            "target_regime": None,
            "target_session": None,
            "target_entry_model": None,
            "observe_metrics": [metric] if metric else [],
            "promotion_guardrails": [
                "do_not_weaken_safety_or_structural_gates",
                "do_not_treat_research_output_as_live_approval",
            ],
            "confidence": confidence,
            "sample_note": cls._sample_note(samples),
        }

        if focus_name == "family_information_failure":
            action.update(
                {
                    "recommended_action": "run_shadow_exit_review",
                    "recommended_scope": "family",
                    "recommended_reason": "information_failure_rate is elevated for this family",
                    "shadow_experiment_type": "exit_failure_review",
                    "target_family": bucket,
                    "observe_metrics": ["information_failure_rate", "forced_exit_rate", "post_cost_ev"],
                    "promotion_guardrails": [
                        "do_not_promote_if_information_failure_persists",
                        "do_not_weaken_safety_or_structural_gates",
                    ],
                }
            )
        elif focus_name == "family_forced_exit":
            action.update(
                {
                    "recommended_action": "run_shadow_exit_timing_review",
                    "recommended_scope": "family",
                    "recommended_reason": "forced_exit_rate is elevated for this family",
                    "shadow_experiment_type": "exit_timing_review",
                    "target_family": bucket,
                    "observe_metrics": ["forced_exit_rate", "time_failure_ratio", "avg_hold_bars", "post_cost_ev"],
                    "promotion_guardrails": ["do_not_promote_if_forced_exit_remains_elevated"],
                }
            )
        elif focus_name == "regime_negative_ev":
            action.update(
                {
                    "recommended_action": "run_shadow_regime_filter_review",
                    "recommended_scope": "regime",
                    "recommended_reason": "post-cost EV is negative in this regime",
                    "shadow_experiment_type": "regime_filter_review",
                    "target_regime": bucket,
                    "observe_metrics": ["ev", "p5_ev", "max_drawdown", "candidate_pass_rate"],
                    "promotion_guardrails": ["do_not_expand_rollout_until_ev_is_non_negative"],
                }
            )
        elif focus_name == "session_negative_ev":
            action.update(
                {
                    "recommended_action": "run_shadow_session_review",
                    "recommended_scope": "session",
                    "recommended_reason": "post-cost EV is negative in this session",
                    "shadow_experiment_type": "session_filter_review",
                    "target_session": bucket,
                    "observe_metrics": ["ev", "fill_rate", "slippage_bps", "candidate_pass_rate"],
                    "promotion_guardrails": ["do_not_harden_session_policy_without_repeat_evidence"],
                }
            )
        elif focus_name == "entry_model_fill_rate":
            action.update(
                {
                    "recommended_action": "run_shadow_entry_model_fill_review",
                    "recommended_scope": "entry_model",
                    "recommended_reason": "fill_rate is weak for this entry model",
                    "shadow_experiment_type": "entry_fill_review",
                    "target_entry_model": bucket.upper(),
                    "observe_metrics": ["fill_rate", "unfilled_rate", "timed_out_after_trigger", "expected_ev_at_size_r"],
                    "promotion_guardrails": ["do_not_promote_if_fill_rate_remains_subscale"],
                }
            )
        elif focus_name == "entry_model_slippage":
            action.update(
                {
                    "recommended_action": "run_shadow_entry_cost_review",
                    "recommended_scope": "entry_model",
                    "recommended_reason": "slippage is elevated for this entry model",
                    "shadow_experiment_type": "entry_cost_review",
                    "target_entry_model": bucket.upper(),
                    "observe_metrics": ["avg_slippage_bps", "avg_entry_latency_seconds", "post_cost_ev"],
                    "promotion_guardrails": ["do_not_promote_if_cost_drag_persists"],
                }
            )
        elif focus_name == "post_cost_ev_deterioration":
            action.update(
                {
                    "recommended_action": "run_shadow_cost_stress_review",
                    "recommended_scope": "global",
                    "recommended_reason": "stressed cost materially weakens EV",
                    "shadow_experiment_type": "cost_stress_review",
                    "observe_metrics": ["baseline_cost_ev", "stressed_cost_ev", "delta_ev_stressed_minus_baseline"],
                    "promotion_guardrails": ["do_not_expand_rollout_while_cost_stress_remains_negative"],
                }
            )
        return action

    @classmethod
    def _recommended_actions(cls, alignment: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not alignment:
            return []
        actions = [cls._recommended_action(item) for item in list(alignment.get("focus_items") or [])]
        confidence_rank = {"high": 2, "medium": 1, "low": 0}
        actions.sort(
            key=lambda item: (
                0 if str(item.get("focus") or "") == "post_cost_ev_deterioration" else 1,
                -int(item.get("aligned_candidates", 0) or 0),
                -int(confidence_rank.get(str(item.get("confidence") or "low"), 0)),
                -abs(float(item.get("value", 0.0) or 0.0)),
                str(item.get("focus") or ""),
                str(item.get("bucket") or ""),
            )
        )
        return actions[:5]

    @staticmethod
    def _recommended_action_summary(actions: list[dict[str, Any]], *, analysis_symbol: str | None) -> dict[str, Any] | None:
        if not actions:
            return None
        top = dict(actions[0])
        return {
            "analysis_symbol": analysis_symbol,
            "recommended_action": top.get("recommended_action"),
            "recommended_scope": top.get("recommended_scope"),
            "recommended_reason": top.get("recommended_reason"),
            "shadow_experiment_type": top.get("shadow_experiment_type"),
            "bucket": top.get("bucket"),
            "focus": top.get("focus"),
            "confidence": top.get("confidence"),
            "sample_note": top.get("sample_note"),
            "aligned_candidates": int(top.get("aligned_candidates", 0) or 0),
        }

    @staticmethod
    def _target_label(action: dict[str, Any]) -> str:
        if action.get("target_family"):
            return f"family={action['target_family']}"
        if action.get("target_regime"):
            return f"regime={action['target_regime']}"
        if action.get("target_session"):
            return f"session={action['target_session']}"
        if action.get("target_entry_model"):
            return f"entry_model={action['target_entry_model']}"
        return "global"

    @classmethod
    def _shadow_experiment_template(cls, action: dict[str, Any], *, analysis_symbol: str | None) -> dict[str, Any]:
        target = cls._target_label(action)
        template = {
            "experiment_id": "shadow_quality_focus_global",
            "title": "Quality Focus Review",
            "objective": "Review the highlighted quality focus in shadow mode before any policy change.",
            "recommended_action": action.get("recommended_action"),
            "recommended_scope": action.get("recommended_scope"),
            "shadow_experiment_type": action.get("shadow_experiment_type"),
            "analysis_symbol": analysis_symbol,
            "target": target,
            "focus": action.get("focus"),
            "bucket": action.get("bucket"),
            "steps": [
                "isolate matched alpha-research candidates for this focus before widening scope",
                "compare the focus bucket against recent shadow outcomes and execution cost",
                "treat the result as research evidence only and keep hard gates unchanged",
            ],
            "observe_metrics": list(action.get("observe_metrics") or []),
            "success_criteria": [
                "repeat evidence suggests the focus can improve without weakening hard gates",
                "post-cost EV does not deteriorate while investigating the focus",
            ],
            "stop_conditions": [
                "sample is too thin to support a repeatable conclusion",
                "the review surfaces safety or structural issues",
            ],
            "promotion_guardrails": list(action.get("promotion_guardrails") or []),
            "confidence": action.get("confidence"),
            "sample_note": action.get("sample_note"),
        }

        recommended_action = str(action.get("recommended_action") or "")
        if recommended_action == "run_shadow_exit_review":
            template.update(
                {
                    "experiment_id": "shadow_exit_review_family",
                    "title": "Family Exit Failure Review",
                    "objective": "Determine whether elevated information failure in this family is an exit issue or a deeper quality problem.",
                    "steps": [
                        "collect recent candidates for the target family in shadow mode",
                        "compare information failure against forced exit and time failure patterns",
                        "review whether the family keeps post-cost EV after filtering obvious failures",
                    ],
                    "success_criteria": [
                        "information failure looks reducible without weakening hard gates",
                        "forced exit overlap trends lower while post-cost EV remains stable",
                    ],
                    "stop_conditions": [
                        "sample is too thin to separate exit failure from noise",
                        "the same family also shows safety or structural violations",
                    ],
                }
            )
        elif recommended_action == "run_shadow_exit_timing_review":
            template.update(
                {
                    "experiment_id": "shadow_exit_timing_family",
                    "title": "Family Exit Timing Review",
                    "objective": "Check whether forced exits come from timing drift rather than from weak signal quality.",
                    "steps": [
                        "review target family trades that ended in forced exit",
                        "compare hold-time distribution against time failure and drawdown drift",
                        "test whether shadow timing adjustments improve post-cost EV without larger tail loss",
                    ],
                    "success_criteria": [
                        "a narrower exit-timing hypothesis emerges for the family",
                        "forced exit pressure looks reducible without worse drawdown",
                    ],
                    "stop_conditions": [
                        "holding longer only increases drawdown without EV recovery",
                        "sample is too small to isolate a timing effect",
                    ],
                }
            )
        elif recommended_action == "run_shadow_regime_filter_review":
            template.update(
                {
                    "experiment_id": "shadow_regime_filter",
                    "title": "Regime Filter Review",
                    "objective": "Verify that the target regime consistently carries negative post-cost EV.",
                    "steps": [
                        "group matched candidates by the target regime",
                        "compare regime EV and tail outcomes against neighboring regimes",
                        "keep any regime change as research-only until repeat evidence accumulates",
                    ],
                    "success_criteria": [
                        "negative EV in the target regime remains repeatable",
                        "the regime split is clearer than simple noise or sample imbalance",
                    ],
                    "stop_conditions": [
                        "regime differences are inconsistent across recent samples",
                        "sample is too thin to justify a regime conclusion",
                    ],
                }
            )
        elif recommended_action == "run_shadow_session_review":
            template.update(
                {
                    "experiment_id": "shadow_session_filter",
                    "title": "Session Review",
                    "objective": "Check whether the target session consistently degrades cost-adjusted performance.",
                    "steps": [
                        "collect matched candidates for the target session",
                        "compare fill rate, slippage, and EV against other sessions",
                        "treat any session gating idea as research-only until repeat evidence appears",
                    ],
                    "success_criteria": [
                        "the target session repeatedly underperforms after costs",
                        "session-specific friction is visible in both fill and EV data",
                    ],
                    "stop_conditions": [
                        "session differences disappear after a small sample expansion",
                        "the target session does not show repeatable cost drag",
                    ],
                }
            )
        elif recommended_action == "run_shadow_entry_model_fill_review":
            template.update(
                {
                    "experiment_id": "shadow_entry_model_fill",
                    "title": "Entry Model Fill Review",
                    "objective": "Separate weak fill behavior from broader execution friction for the target entry model.",
                    "steps": [
                        "group matched candidates by the target entry model",
                        "compare fill rate, unfilled rate, and timed-out triggers",
                        "review whether better fill behavior keeps expected EV at size",
                    ],
                    "success_criteria": [
                        "fill quality looks improvable without unacceptable cost drag",
                        "expected EV at size does not collapse when fill behavior improves",
                    ],
                    "stop_conditions": [
                        "better fill comes only with materially worse slippage",
                        "sample is too thin to separate fill issues from noise",
                    ],
                }
            )
        elif recommended_action == "run_shadow_entry_cost_review":
            template.update(
                {
                    "experiment_id": "shadow_entry_model_cost",
                    "title": "Entry Cost Review",
                    "objective": "Verify whether cost drag is structurally tied to the target entry model.",
                    "steps": [
                        "collect matched candidates for the target entry model",
                        "compare slippage, entry latency, and post-cost EV against alternative entry models",
                        "treat any entry-model policy change as research-only until cost drag is repeatable",
                    ],
                    "success_criteria": [
                        "cost drag remains concentrated in the target entry model",
                        "latency and slippage explain the EV deterioration clearly",
                    ],
                    "stop_conditions": [
                        "cost drag does not persist across recent samples",
                        "the same issue appears across all entry models equally",
                    ],
                }
            )
        elif recommended_action == "run_shadow_cost_stress_review":
            template.update(
                {
                    "experiment_id": "shadow_cost_stress_global",
                    "title": "Cost Stress Review",
                    "objective": "Measure how much stressed execution costs weaken strategy EV before any rollout expansion.",
                    "steps": [
                        "compare baseline and stressed cost assumptions on recent matched candidates",
                        "review whether EV deterioration is concentrated in a small set of families or entry models",
                        "keep rollout unchanged until stressed cost behavior improves in research",
                    ],
                    "success_criteria": [
                        "stressed cost EV stabilizes near baseline behavior",
                        "cost sensitivity no longer dominates the decomposition focus",
                    ],
                    "stop_conditions": [
                        "stressed EV remains negative across repeated windows",
                        "cost deterioration broadens to additional families or entry models",
                    ],
                }
            )
        return template

    @classmethod
    def _shadow_experiment_templates(
        cls,
        actions: list[dict[str, Any]],
        *,
        analysis_symbol: str | None,
    ) -> list[dict[str, Any]]:
        return [cls._shadow_experiment_template(action, analysis_symbol=analysis_symbol) for action in actions]

    @staticmethod
    def _top_shadow_experiment(
        templates: list[dict[str, Any]],
        *,
        analysis_symbol: str | None,
    ) -> dict[str, Any] | None:
        if not templates:
            return None
        top = dict(templates[0])
        return {
            "analysis_symbol": analysis_symbol,
            "experiment_id": top.get("experiment_id"),
            "title": top.get("title"),
            "objective": top.get("objective"),
            "recommended_action": top.get("recommended_action"),
            "recommended_scope": top.get("recommended_scope"),
            "shadow_experiment_type": top.get("shadow_experiment_type"),
            "target": top.get("target"),
            "focus": top.get("focus"),
            "bucket": top.get("bucket"),
            "confidence": top.get("confidence"),
            "sample_note": top.get("sample_note"),
            "observe_metrics": list(top.get("observe_metrics") or []),
            "success_criteria": list(top.get("success_criteria") or []),
            "stop_conditions": list(top.get("stop_conditions") or []),
            "promotion_guardrails": list(top.get("promotion_guardrails") or []),
        }

    @classmethod
    def _near_miss_reason_summary(
        cls,
        *,
        rows: list[dict[str, Any]],
        summary: dict[str, Any],
        priorities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "candidate_count": int(summary.get("alpha_research_candidate_count", 0) or 0),
            "reason_counts": {
                str(row.get("reason") or "unknown"): int(row.get("candidates", 0) or 0)
                for row in priorities
            },
            "top_reason": summary.get("top_reason"),
            "top_family": summary.get("top_family"),
            "top_regime": summary.get("top_regime"),
            "top_session": summary.get("top_session"),
            "avg_softened_risk_r": float(summary.get("avg_softened_risk_r", 0.0) or 0.0),
            "matched_focus_candidate_count": sum(
                1 for row in rows if int(row.get("research_focus_match_count", 0) or 0) > 0
            ),
        }

    @staticmethod
    def _focus_alignment_summary(
        alignment: dict[str, Any] | None,
        *,
        candidate_count: int,
    ) -> dict[str, Any] | None:
        if not alignment:
            return None
        aligned = int(alignment.get("aligned_candidate_count", 0) or 0)
        return {
            "aligned_candidate_count": aligned,
            "top_focus": alignment.get("top_focus"),
            "top_bucket": alignment.get("top_bucket"),
            "top_focus_share_of_candidates": round((aligned / candidate_count), 4) if candidate_count > 0 else 0.0,
            "focus_items": list(alignment.get("focus_items") or []),
        }

    @classmethod
    def _alignment_strength(
        cls,
        *,
        matched_candidates: int,
        profitable_rate_from_closed: float,
        baseline_cost_profitable_rate_from_closed: float,
        matching_reasons: int,
    ) -> str:
        if matched_candidates >= 2 and matching_reasons > 0 and baseline_cost_profitable_rate_from_closed <= 0.5:
            return "high"
        if matched_candidates >= 1 and (
            matching_reasons > 0 or profitable_rate_from_closed <= 0.5 or baseline_cost_profitable_rate_from_closed <= 0.5
        ):
            return "medium"
        return "low"

    @classmethod
    def _outcome_alignment_summary(
        cls,
        *,
        score_to_outcome_funnel: dict[str, Any] | None,
        alignment: dict[str, Any] | None,
        priorities: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        payload = dict(score_to_outcome_funnel or {})
        if not payload:
            return None

        decomposition = dict(payload.get("decomposition") or {})
        focus_items = list((alignment or {}).get("focus_items") or [])
        signals: list[dict[str, Any]] = []
        matching_reasons: set[str] = set()

        for item in focus_items:
            focus_name = str(item.get("focus") or "")
            axis = cls._focus_axis(focus_name)
            if axis not in {"family", "regime", "session"}:
                continue
            bucket = str(item.get("bucket") or "")
            if not bucket:
                continue
            decomposition_rows = list(decomposition.get(axis) or [])
            matched_bucket = next((dict(row) for row in decomposition_rows if str(row.get("key") or "") == bucket), None)
            if not matched_bucket:
                continue

            axis_field = f"top_{axis}"
            matched_priority_reasons = [
                str(row.get("reason") or "unknown")
                for row in priorities
                if str(row.get(axis_field) or "") == bucket
            ]
            matching_reasons.update(matched_priority_reasons)
            profitable_rate = float(matched_bucket.get("profitable_rate_from_closed", 0.0) or 0.0)
            baseline_rate = float(matched_bucket.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
            signals.append(
                {
                    "axis": axis,
                    "focus": focus_name,
                    "bucket": bucket,
                    "matched_candidates": int(item.get("candidates", 0) or 0),
                    "runtime_candidates": int(matched_bucket.get("runtime_candidates", 0) or 0),
                    "accepted_candidates": int(matched_bucket.get("accepted_candidates", 0) or 0),
                    "submitted": int(matched_bucket.get("submitted", 0) or 0),
                    "closed": int(matched_bucket.get("closed", 0) or 0),
                    "baseline_cost_profitable": int(matched_bucket.get("baseline_cost_profitable", 0) or 0),
                    "profitable_rate_from_closed": profitable_rate,
                    "baseline_cost_profitable_rate_from_closed": baseline_rate,
                    "matching_reasons": matched_priority_reasons,
                    "alignment_strength": cls._alignment_strength(
                        matched_candidates=int(item.get("candidates", 0) or 0),
                        profitable_rate_from_closed=profitable_rate,
                        baseline_cost_profitable_rate_from_closed=baseline_rate,
                        matching_reasons=len(matched_priority_reasons),
                    ),
                }
            )

        strength_rank = {"high": 2, "medium": 1, "low": 0}
        signals.sort(
            key=lambda row: (
                -int(strength_rank.get(str(row.get("alignment_strength") or "low"), 0)),
                -int(row.get("matched_candidates", 0) or 0),
                -int(row.get("runtime_candidates", 0) or 0),
                str(row.get("axis") or ""),
                str(row.get("bucket") or ""),
            )
        )

        return {
            "available": True,
            "top_family_bottleneck": dict((list(decomposition.get("family") or [])[:1] or [{}])[0]),
            "top_regime_bottleneck": dict((list(decomposition.get("regime") or [])[:1] or [{}])[0]),
            "top_session_bottleneck": dict((list(decomposition.get("session") or [])[:1] or [{}])[0]),
            "matching_softening_reasons": sorted(matching_reasons),
            "alignment_signals": signals,
        }

    @classmethod
    def _execution_drag_conflict(
        cls,
        *,
        focus_name: str,
        execution_degradation_advisory: dict[str, Any] | None,
    ) -> bool:
        advisory = dict(execution_degradation_advisory or {})
        status = str(advisory.get("status", "healthy") or "healthy").lower()
        if status == "healthy":
            return False
        if focus_name in {
            "family_information_failure",
            "family_forced_exit",
            "entry_model_fill_rate",
            "entry_model_slippage",
            "post_cost_ev_deterioration",
        }:
            return True
        return status == "manual_review"

    @classmethod
    def _false_negative_suspects(
        cls,
        *,
        rows: list[dict[str, Any]],
        alignment: dict[str, Any] | None,
        outcome_alignment_summary: dict[str, Any] | None,
        execution_degradation_advisory: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        signals = {
            (str(row.get("axis") or ""), str(row.get("bucket") or "")): dict(row)
            for row in list((outcome_alignment_summary or {}).get("alignment_signals") or [])
        }
        if not signals:
            return []

        suspects: list[dict[str, Any]] = []
        for focus in list((alignment or {}).get("focus_items") or []):
            focus_name = str(focus.get("focus") or "")
            axis = cls._focus_axis(focus_name)
            bucket = str(focus.get("bucket") or "")
            signal = signals.get((axis, bucket))
            if not signal:
                continue
            matched_rows = [
                row
                for row in rows
                if any(
                    str(match.get("focus") or "") == focus_name and str(match.get("bucket") or "") == bucket
                    for match in list(row.get("research_focus_matches") or [])
                )
            ]
            if not matched_rows:
                continue

            expected_values = [
                float(row.get("expected_ev_at_recommended_size_r", row.get("expected_ev_r", 0.0)) or 0.0)
                for row in matched_rows
            ]
            softened_risk_values = [
                float(row.get("alpha_research_softened_risk_r", 0.0) or 0.0)
                for row in matched_rows
            ]
            reason_counts = Counter(
                str(row.get("alpha_research_reason") or row.get("block_reason") or "unknown")
                for row in matched_rows
            )
            symbol_counts = Counter(str(row.get("symbol") or "") for row in matched_rows)
            samples = int(focus.get("samples", 0) or 0)
            suspects.append(
                {
                    "reason": cls._top_key(reason_counts),
                    "axis": axis,
                    "bucket": bucket,
                    "matched_candidates": len(matched_rows),
                    "top_symbol": cls._top_key(symbol_counts),
                    "avg_expected_ev_r": cls._avg(expected_values),
                    "avg_softened_risk_r": cls._avg(softened_risk_values),
                    "alignment_strength": signal.get("alignment_strength", "low"),
                    "execution_drag_conflict": cls._execution_drag_conflict(
                        focus_name=focus_name,
                        execution_degradation_advisory=execution_degradation_advisory,
                    ),
                    "confidence": cls._confidence(samples),
                    "sample_note": cls._sample_note(samples),
                    "why_suspected": (
                        f"{focus_name} matches an outcome bottleneck at {axis}={bucket} with repeated near-miss candidates"
                    ),
                }
            )

        strength_rank = {"high": 2, "medium": 1, "low": 0}
        suspects.sort(
            key=lambda row: (
                bool(row.get("execution_drag_conflict")),
                -int(strength_rank.get(str(row.get("alignment_strength") or "low"), 0)),
                -int(row.get("matched_candidates", 0) or 0),
                -float(row.get("avg_expected_ev_r", 0.0) or 0.0),
                str(row.get("bucket") or ""),
            )
        )
        return suspects[:5]

    @classmethod
    def _alpha_research_evidence_summary(
        cls,
        *,
        rows: list[dict[str, Any]],
        summary: dict[str, Any],
        priorities: list[dict[str, Any]],
        research_focus_alignment: dict[str, Any] | None,
        score_to_outcome_funnel: dict[str, Any] | None,
        execution_degradation_advisory: dict[str, Any] | None,
        analysis_symbol: str | None,
    ) -> dict[str, Any] | None:
        if not rows:
            return None
        focus_alignment_summary = cls._focus_alignment_summary(
            research_focus_alignment,
            candidate_count=len(rows),
        )
        outcome_alignment_summary = cls._outcome_alignment_summary(
            score_to_outcome_funnel=score_to_outcome_funnel,
            alignment=research_focus_alignment,
            priorities=priorities,
        )
        return {
            "available": True,
            "analysis_symbol": analysis_symbol,
            "coverage_note": (
                "false_negative_suspects are heuristic only; runtime selection is snapshot data and "
                "execution outcomes are windowed history."
            ),
            "near_miss_reason_summary": cls._near_miss_reason_summary(
                rows=rows,
                summary=summary,
                priorities=priorities,
            ),
            "focus_alignment_summary": focus_alignment_summary,
            "outcome_alignment_summary": outcome_alignment_summary,
            "false_negative_suspects": cls._false_negative_suspects(
                rows=rows,
                alignment=research_focus_alignment,
                outcome_alignment_summary=outcome_alignment_summary,
                execution_degradation_advisory=execution_degradation_advisory,
            ),
        }

    @classmethod
    def _softening_candidate_review(
        cls,
        *,
        evidence_summary: dict[str, Any] | None,
        recommended_actions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        payload = dict(evidence_summary or {})
        suspects = [
            dict(row)
            for row in list(payload.get("false_negative_suspects") or [])
            if str(row.get("reason") or "unknown") in _SOFTENING_RESEARCH_REASONS
        ]
        if not suspects:
            return None

        action_by_bucket = {
            (str(row.get("focus") or ""), str(row.get("bucket") or "")): dict(row)
            for row in recommended_actions
        }
        confidence_rank = {"high": 2, "medium": 1, "low": 0}
        review_items: list[dict[str, Any]] = []
        for suspect in suspects:
            axis = str(suspect.get("axis") or "global")
            bucket = str(suspect.get("bucket") or "")
            action = next(
                (
                    row
                    for row in recommended_actions
                    if str(row.get("bucket") or "") == bucket
                ),
                {},
            )
            conflict = bool(suspect.get("execution_drag_conflict", False))
            alignment_strength = str(suspect.get("alignment_strength") or "low")
            priority = "p2"
            if not conflict and alignment_strength == "high":
                priority = "p0"
            elif not conflict and alignment_strength == "medium":
                priority = "p1"
            elif conflict and alignment_strength != "low":
                priority = "p2"
            else:
                priority = "p3"
            review_items.append(
                {
                    "reason": suspect.get("reason"),
                    "bucket": bucket,
                    "axis": axis,
                    "review_priority": priority,
                    "recommended_research_action": action.get("recommended_action", "run_shadow_quality_review"),
                    "why_now": suspect.get("why_suspected"),
                    "blocking_guardrails": [
                        "keep_safety_and_structural_gates_unchanged",
                        "treat_output_as_research_only",
                    ],
                    "required_evidence": list(action.get("observe_metrics") or []),
                    "execution_drag_conflict": conflict,
                    "confidence": suspect.get("confidence"),
                    "sample_note": suspect.get("sample_note"),
                }
            )

        review_items.sort(
            key=lambda row: (
                str(row.get("review_priority") or "p9"),
                bool(row.get("execution_drag_conflict", False)),
                -int(confidence_rank.get(str(row.get("confidence") or "low"), 0)),
                str(row.get("bucket") or ""),
            )
        )
        return {
            "available": True,
            "top_candidate": dict((review_items[:1] or [{}])[0]),
            "review_items": review_items[:5],
        }

    @classmethod
    def _promotion_watchlist(
        cls,
        *,
        evidence_summary: dict[str, Any] | None,
        recommended_actions: list[dict[str, Any]],
        top_shadow_experiment: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = dict(evidence_summary or {})
        suspects = list(payload.get("false_negative_suspects") or [])
        if not suspects or not recommended_actions:
            return None

        top_experiment = dict(top_shadow_experiment or {})
        watch_items: list[dict[str, Any]] = []
        confidence_rank = {"high": 2, "medium": 1, "low": 0}
        for suspect in suspects:
            bucket = str(suspect.get("bucket") or "")
            action = next(
                (
                    row
                    for row in recommended_actions
                    if str(row.get("bucket") or "") == bucket
                ),
                {},
            )
            confidence = str(suspect.get("confidence") or "low")
            conflict = bool(suspect.get("execution_drag_conflict", False))
            not_ready_reason = None
            if conflict:
                not_ready_reason = "execution_drag_conflict"
            elif confidence == "low":
                not_ready_reason = "thin_sample"
            elif str(suspect.get("alignment_strength") or "low") == "low":
                not_ready_reason = "weak_alignment"

            watch_items.append(
                {
                    "focus": action.get("focus") or f"{suspect.get('axis')}:{bucket}",
                    "bucket": bucket,
                    "matched_candidates": int(suspect.get("matched_candidates", 0) or 0),
                    "recent_shadow_template": top_experiment.get("experiment_id")
                    if str(top_experiment.get("bucket") or "") == bucket
                    else action.get("shadow_experiment_type"),
                    "post_cost_condition": (
                        "needs_baseline_cost_stability"
                        if str(suspect.get("alignment_strength") or "low") != "low"
                        else "insufficient_post_cost_alignment"
                    ),
                    "execution_health_condition": "conflict"
                    if conflict
                    else "runtime_execution_ok_for_research_watch",
                    "confidence": confidence,
                    "sample_note": suspect.get("sample_note"),
                    "why_watch": (
                        f"{bucket} shows repeated near-miss alignment with a viable research action but is still research-only."
                    ),
                    "not_ready_reason": not_ready_reason,
                }
            )

        watch_items.sort(
            key=lambda row: (
                1 if row.get("not_ready_reason") else 0,
                -int(confidence_rank.get(str(row.get("confidence") or "low"), 0)),
                -int(row.get("matched_candidates", 0) or 0),
                str(row.get("bucket") or ""),
            )
        )
        return {
            "available": True,
            "watchlist_count": len(watch_items),
            "watch_items": watch_items[:5],
        }

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"alpha_research_pipeline_{payload['universe']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"

        summary = dict(payload.get("summary") or {})
        research_focus_alignment = dict(payload.get("research_focus_alignment") or {})
        recommended_action_summary = dict(payload.get("recommended_action_summary") or {})
        evidence_summary = dict(payload.get("alpha_research_evidence_summary") or {})
        softening_review = dict(payload.get("softening_candidate_review") or {})
        promotion_watchlist = dict(payload.get("promotion_watchlist") or {})
        experiment_sequence = dict(payload.get("experiment_sequence") or {})
        reason_summary = dict(evidence_summary.get("near_miss_reason_summary") or {})
        focus_summary = dict(evidence_summary.get("focus_alignment_summary") or {})
        outcome_summary = dict(evidence_summary.get("outcome_alignment_summary") or {})
        lines = [
            f"# Alpha Research Pipeline: {payload['universe']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- available: {payload['available']}",
            f"- reason: {payload['reason']}",
            f"- focus_symbol: {payload.get('focus_symbol')}",
            f"- analysis_symbol: {payload.get('analysis_symbol')}",
            "",
            "## Summary",
            f"- alpha_research_candidate_count: {int(summary.get('alpha_research_candidate_count', 0))}",
            f"- focus_symbol_candidate_count: {int(summary.get('focus_symbol_candidate_count', 0))}",
            f"- top_reason: {summary.get('top_reason')}",
            f"- top_family: {summary.get('top_family')}",
            f"- top_regime: {summary.get('top_regime')}",
            f"- top_session: {summary.get('top_session')}",
            f"- avg_softened_risk_r: {float(summary.get('avg_softened_risk_r', 0.0)):.4f}",
            f"- max_expected_ev_at_size_r: {float(summary.get('max_expected_ev_at_size_r', 0.0)):.4f}",
            "",
            "## Research Focus Alignment",
            f"- available: {bool(research_focus_alignment.get('available', False))}",
            f"- analysis_symbol: {research_focus_alignment.get('analysis_symbol')}",
            f"- aligned_candidate_count: {int(research_focus_alignment.get('aligned_candidate_count', 0))}",
            f"- top_focus: {research_focus_alignment.get('top_focus')}",
            f"- top_bucket: {research_focus_alignment.get('top_bucket')}",
            "",
            "## Recommended Action",
            f"- recommended_action: {recommended_action_summary.get('recommended_action')}",
            f"- recommended_scope: {recommended_action_summary.get('recommended_scope')}",
            f"- recommended_reason: {recommended_action_summary.get('recommended_reason')}",
            f"- shadow_experiment_type: {recommended_action_summary.get('shadow_experiment_type')}",
            f"- confidence: {recommended_action_summary.get('confidence')}",
            f"- sample_note: {recommended_action_summary.get('sample_note')}",
            f"- deferred_by_experiment_sequence: {bool(recommended_action_summary.get('deferred_by_experiment_sequence', False))}",
            f"- current_priority_experiment: {recommended_action_summary.get('current_priority_experiment')}",
            f"- current_priority_action: {recommended_action_summary.get('current_priority_action')}",
            f"- sequencing_reason: {recommended_action_summary.get('sequencing_reason')}",
            "",
            "## Experiment Sequence",
            f"- state: {experiment_sequence.get('state')}",
            f"- entry_timing_locked: {bool(experiment_sequence.get('entry_timing_locked', False))}",
            f"- execution_style_locked: {bool(experiment_sequence.get('execution_style_locked', False))}",
            f"- exit_optimization_allowed: {bool(experiment_sequence.get('exit_optimization_allowed', False))}",
            f"- current_priority_experiment: {experiment_sequence.get('current_priority_experiment')}",
            f"- current_priority_action: {experiment_sequence.get('current_priority_action')}",
            f"- summary: {experiment_sequence.get('summary')}",
            "",
            "## Evidence Summary",
            f"- available: {bool(evidence_summary.get('available', False))}",
            f"- analysis_symbol: {evidence_summary.get('analysis_symbol')}",
            f"- coverage_note: {evidence_summary.get('coverage_note')}",
            f"- near_miss_top_reason: {reason_summary.get('top_reason')}",
            f"- focus_aligned_candidates: {int(focus_summary.get('aligned_candidate_count', 0) or 0)}",
            f"- focus_top: {focus_summary.get('top_focus')}:{focus_summary.get('top_bucket')}",
            f"- top_family_bottleneck: {dict(outcome_summary.get('top_family_bottleneck') or {}).get('key')}",
            f"- top_regime_bottleneck: {dict(outcome_summary.get('top_regime_bottleneck') or {}).get('key')}",
            f"- top_session_bottleneck: {dict(outcome_summary.get('top_session_bottleneck') or {}).get('key')}",
            "",
            "## Recommended Actions",
        ]
        for row in payload.get("recommended_actions") or []:
            lines.append(
                f"- {row['recommended_action']} [{row['recommended_scope']}] bucket={row.get('bucket')}: "
                f"reason={row.get('recommended_reason')}, aligned_candidates={int(row.get('aligned_candidates', 0))}, "
                f"confidence={row.get('confidence')}, observe={row.get('observe_metrics')}"
            )
        lines.append("")
        lines.append("## Focus Priorities")
        for row in research_focus_alignment.get("focus_items") or []:
            lines.append(
                f"- focus {row['focus']}:{row['bucket']}: candidates={int(row.get('candidates', 0))}, "
                f"metric={row.get('metric')}, value={float(row.get('value', 0.0)):.4f}, "
                f"top_reason={row.get('top_reason')}, top_symbol={row.get('top_symbol')}"
            )
        lines.extend(["", "## False Negative Suspects"])
        for row in evidence_summary.get("false_negative_suspects") or []:
            lines.append(
                f"- {row.get('axis')}:{row.get('bucket')}: reason={row.get('reason')}, "
                f"matched_candidates={int(row.get('matched_candidates', 0) or 0)}, "
                f"alignment_strength={row.get('alignment_strength')}, "
                f"execution_drag_conflict={bool(row.get('execution_drag_conflict', False))}, "
                f"confidence={row.get('confidence')}"
            )
        lines.extend(["", "## Softening Candidate Review"])
        lines.append(f"- available: {bool(softening_review.get('available', False))}")
        top_review = dict(softening_review.get("top_candidate") or {})
        lines.append(
            f"- top_candidate: {top_review.get('axis')}:{top_review.get('bucket')} "
            f"reason={top_review.get('reason')} priority={top_review.get('review_priority')} "
            f"action={top_review.get('recommended_research_action')}"
        )
        for row in softening_review.get("review_items") or []:
            lines.append(
                f"- {row.get('review_priority')} {row.get('axis')}:{row.get('bucket')}: "
                f"reason={row.get('reason')}, action={row.get('recommended_research_action')}, "
                f"execution_drag_conflict={bool(row.get('execution_drag_conflict', False))}, "
                f"confidence={row.get('confidence')}"
            )
        lines.extend(["", "## Promotion Watchlist"])
        lines.append(f"- available: {bool(promotion_watchlist.get('available', False))}")
        lines.append(f"- watchlist_count: {int(promotion_watchlist.get('watchlist_count', 0) or 0)}")
        for row in promotion_watchlist.get("watch_items") or []:
            lines.append(
                f"- {row.get('bucket')}: focus={row.get('focus')}, "
                f"matched_candidates={int(row.get('matched_candidates', 0) or 0)}, "
                f"template={row.get('recent_shadow_template')}, "
                f"execution_health_condition={row.get('execution_health_condition')}, "
                f"not_ready_reason={row.get('not_ready_reason')}"
            )
        lines.extend(["", "## Priorities"])
        for row in payload.get("priorities") or []:
            lines.append(
                f"- {row['reason']}: candidates={int(row.get('candidates', 0))}, "
                f"top_family={row.get('top_family')}, top_regime={row.get('top_regime')}, "
                f"top_session={row.get('top_session')}, focus_match_count={int(row.get('focus_match_count', 0))}, "
                f"top_focus={row.get('top_focus')}, avg_expected_ev_r={float(row.get('avg_expected_ev_r', 0.0)):.4f}, "
                f"avg_softened_risk_r={float(row.get('avg_softened_risk_r', 0.0)):.4f}"
            )
        lines.extend(["", "## Candidates"])
        for row in payload.get("candidates") or []:
            focus_labels = ",".join(
                f"{match.get('focus')}:{match.get('bucket')}" for match in list(row.get("research_focus_matches") or [])
            )
            if not focus_labels:
                focus_labels = "none"
            lines.append(
                f"- {row['symbol']} {row['direction']} {row['entry_model']}: "
                f"reason={row.get('alpha_research_reason')}, gap={float(row.get('alpha_research_gap', 0.0)):.4f}, "
                f"softened_risk={float(row.get('alpha_research_softened_risk_r', 0.0)):.4f}R, "
                f"expected_ev_r={float(row.get('expected_ev_r', 0.0)):.4f}, "
                f"expected_ev_at_size_r={float(row.get('expected_ev_at_recommended_size_r', 0.0)):.4f}, "
                f"focus_matches={int(row.get('research_focus_match_count', 0))}, "
                f"focus_labels={focus_labels}"
            )
        lines.extend(["", "## Next Steps"])
        for step in payload.get("next_steps") or []:
            lines.append(f"- {step}")
        lines.append("")

        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def generate(
        self,
        *,
        universe: str,
        portfolio_budget: dict[str, Any],
        focus_symbol: str | None = None,
        analysis_symbol: str | None = None,
        performance_decomposition_summary: dict[str, Any] | None = None,
        score_to_outcome_funnel: dict[str, Any] | None = None,
        execution_degradation_advisory: dict[str, Any] | None = None,
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        focus = str(focus_symbol or "").upper() or None
        analysis = str(analysis_symbol or focus or "").upper() or None

        if not self.settings.alpha_research_pipeline_enabled:
            return {
                "schema_version": "alpha_research_pipeline_v1",
                "generated_at": now.isoformat(),
                "universe": universe,
                "focus_symbol": focus,
                "analysis_symbol": analysis,
                "available": False,
                "reason": "alpha_research_pipeline_disabled",
                "summary": {},
                "priorities": [],
                "candidates": [],
                "performance_decomposition_summary": performance_decomposition_summary,
                "alpha_research_evidence_summary": None,
                "softening_candidate_review": None,
                "promotion_watchlist": None,
                "research_focus_alignment": None,
                "recommended_action_summary": None,
                "recommended_actions": [],
                "top_shadow_experiment": None,
                "shadow_experiment_templates": [],
                "next_steps": [],
                "report_path": None,
            }

        rows = [dict(row) for row in (portfolio_budget.get("alpha_research_candidates") or []) if row.get("alpha_research_candidate")]
        tuning_focus = list((performance_decomposition_summary or {}).get("tuning_focus") or [])
        for row in rows:
            matches = self._focus_matches(row=row, tuning_focus=tuning_focus)
            row["research_focus_matches"] = matches
            row["research_focus_match_count"] = len(matches)
            row["research_focus_primary_match"] = dict(matches[0]) if matches else None
        rows.sort(key=self._candidate_sort_key, reverse=True)

        symbol_counts = Counter(str(row.get("symbol") or "") for row in rows)
        reason_counts = Counter(str(row.get("alpha_research_reason") or row.get("block_reason") or "unknown") for row in rows)
        family_counts = Counter(str(row.get("strategy_family") or "unknown") for row in rows)
        regime_counts = Counter(str(row.get("regime") or "unknown") for row in rows)
        session_counts = Counter(self._session_state(row) for row in rows)
        focus_rows = [row for row in rows if focus and str(row.get("symbol") or "").upper() == focus]
        research_focus_alignment = self._research_focus_alignment(
            rows=rows,
            analysis_symbol=analysis,
            performance_decomposition_summary=performance_decomposition_summary,
        )
        experiment_sequence = self._experiment_sequence(score_to_outcome_funnel)
        recommended_actions = self._recommended_actions(research_focus_alignment)
        recommended_actions = [
            self._annotate_with_experiment_sequence(row, experiment_sequence=experiment_sequence) or {}
            for row in recommended_actions
        ]
        recommended_action_summary = self._recommended_action_summary(
            recommended_actions,
            analysis_symbol=analysis,
        )
        recommended_action_summary = self._annotate_with_experiment_sequence(
            recommended_action_summary,
            experiment_sequence=experiment_sequence,
        )
        shadow_experiment_templates = self._shadow_experiment_templates(
            recommended_actions,
            analysis_symbol=analysis,
        )
        shadow_experiment_templates = [
            self._annotate_with_experiment_sequence(row, experiment_sequence=experiment_sequence) or {}
            for row in shadow_experiment_templates
        ]
        top_shadow_experiment = self._top_shadow_experiment(
            shadow_experiment_templates,
            analysis_symbol=analysis,
        )
        top_shadow_experiment = self._annotate_with_experiment_sequence(
            top_shadow_experiment,
            experiment_sequence=experiment_sequence,
        )

        priorities: list[dict[str, Any]] = []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            reason = str(row.get("alpha_research_reason") or row.get("block_reason") or "unknown")
            grouped.setdefault(reason, []).append(row)
        for reason, bucket in grouped.items():
            bucket_family = Counter(str(row.get("strategy_family") or "unknown") for row in bucket)
            bucket_regime = Counter(str(row.get("regime") or "unknown") for row in bucket)
            bucket_session = Counter(self._session_state(row) for row in bucket)
            priorities.append(
                {
                    "reason": reason,
                    "candidates": len(bucket),
                    "top_family": self._top_key(bucket_family),
                    "top_regime": self._top_key(bucket_regime),
                    "top_session": self._top_key(bucket_session),
                    "avg_expected_ev_r": round(
                        sum(float(row.get("expected_ev_r", 0.0) or 0.0) for row in bucket) / max(len(bucket), 1),
                        4,
                    ),
                    "avg_softened_risk_r": round(
                        sum(float(row.get("alpha_research_softened_risk_r", 0.0) or 0.0) for row in bucket) / max(len(bucket), 1),
                        4,
                    ),
                    "focus_match_count": sum(int(row.get("research_focus_match_count", 0) or 0) for row in bucket),
                    "top_focus": self._top_key(
                        Counter(
                            str((row.get("research_focus_primary_match") or {}).get("focus") or "none")
                            for row in bucket
                            if row.get("research_focus_primary_match")
                        )
                    ),
                    "symbols": sorted({str(row.get("symbol") or "") for row in bucket}),
                }
            )
        priorities.sort(
            key=lambda item: (
                -int(item.get("focus_match_count", 0)),
                -int(item.get("candidates", 0)),
                -float(item.get("avg_expected_ev_r", 0.0)),
                str(item.get("reason") or ""),
            )
        )

        available = bool(rows)
        summary = {
            "alpha_research_candidate_count": len(rows),
            "focus_symbol_candidate_count": len(focus_rows),
            "top_reason": self._top_key(reason_counts),
            "top_family": self._top_key(family_counts),
            "top_regime": self._top_key(regime_counts),
            "top_session": self._top_key(session_counts),
            "top_symbol": self._top_key(symbol_counts),
            "avg_softened_risk_r": round(
                sum(float(row.get("alpha_research_softened_risk_r", 0.0) or 0.0) for row in rows) / max(len(rows), 1),
                4,
            )
            if rows
            else 0.0,
            "max_expected_ev_at_size_r": round(
                max(float(row.get("expected_ev_at_recommended_size_r", row.get("expected_ev_r", 0.0)) or 0.0) for row in rows),
                4,
            )
            if rows
            else 0.0,
            "analysis_symbol": analysis,
            "aligned_candidate_count": int((research_focus_alignment or {}).get("aligned_candidate_count", 0) or 0),
            "top_alignment_focus": (research_focus_alignment or {}).get("top_focus"),
            "top_alignment_bucket": (research_focus_alignment or {}).get("top_bucket"),
        }
        alpha_research_evidence_summary = self._alpha_research_evidence_summary(
            rows=rows,
            summary=summary,
            priorities=priorities,
            research_focus_alignment=research_focus_alignment,
            score_to_outcome_funnel=score_to_outcome_funnel,
            execution_degradation_advisory=execution_degradation_advisory,
            analysis_symbol=analysis,
        )
        softening_candidate_review = self._softening_candidate_review(
            evidence_summary=alpha_research_evidence_summary,
            recommended_actions=recommended_actions,
        )
        promotion_watchlist = self._promotion_watchlist(
            evidence_summary=alpha_research_evidence_summary,
            recommended_actions=recommended_actions,
            top_shadow_experiment=top_shadow_experiment,
        )

        next_steps = []
        if rows and (research_focus_alignment or {}).get("focus_items"):
            next_steps = [
                "start with alpha-research candidates that match the top decomposition focus before widening softening",
                "use the matched family/regime/session bucket as the first shadow-mode experiment cluster",
                "promote only after the matched focus improves without weakening hard-gate safety or structural controls",
            ]
        elif rows:
            next_steps = [
                "review the top alpha-research candidate in shadow mode before any rollout change",
                "compare repeated near-miss reasons against execution/operator-dashboard quality softening priorities",
                "promote only when research evidence clears the same reason across family, regime, and session clusters",
            ]
        elif focus:
            next_steps = [f"wait for new softening candidates that match {focus} or widen the universe review window"]
        else:
            next_steps = ["wait for new quality-gate near-miss candidates to populate the research backlog"]
        next_steps = self._dedupe_strings(self._sequencing_next_steps(experiment_sequence) + next_steps)

        payload = {
            "schema_version": "alpha_research_pipeline_v1",
            "generated_at": now.isoformat(),
            "universe": universe,
            "focus_symbol": focus,
            "analysis_symbol": analysis,
            "available": available,
            "reason": "ok" if available else "no_alpha_research_candidates",
            "summary": summary,
            "priorities": priorities[:5],
            "candidates": rows[: int(self.settings.alpha_research_max_candidates)],
            "performance_decomposition_summary": performance_decomposition_summary,
            "alpha_research_evidence_summary": alpha_research_evidence_summary,
            "softening_candidate_review": softening_candidate_review,
            "promotion_watchlist": promotion_watchlist,
            "research_focus_alignment": research_focus_alignment,
            "experiment_sequence": experiment_sequence,
            "recommended_action_summary": recommended_action_summary,
            "recommended_actions": recommended_actions,
            "top_shadow_experiment": top_shadow_experiment,
            "shadow_experiment_templates": shadow_experiment_templates,
            "next_steps": next_steps,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
