from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.db.repositories import (
    BinancePositionRepository,
    ExecutionReconciliationEventRepository,
    OrderIntentRepository,
    OrderSubmissionRepository,
)
from app.services.active_contract_replay_baseline import usdt_proxy_rows_for_active_contract
from app.services.edge_experiment_review import build_edge_experiment_review, summarize_edge_experiment_review
from app.services.edge_evolution_rule import build_edge_evolution_rule, summarize_edge_evolution_rule
from app.services.live_route_contract import row_session_name
from app.services.outcome_control_trace import (
    build_outcome_control_trace,
    runtime_outcome_control_trace,
    summarize_outcome_control_trace,
)
from app.services.outcome_attribution import build_outcome_attribution, summarize_outcome_attribution
from app.services.outcome_funnel_operating_kpis import build_outcome_funnel_operating_kpis
from app.services.split_review_followup_ledger import summarize_split_review_followup_ledger


_SEVERITY_ORDER = {
    "INFO": 0,
    "WARNING": 1,
    "CRITICAL": 2,
}

_SAFETY_REASON_PREFIXES = (
    "reconciliation_",
    "kill_switch",
    "close_only",
    "operating_lock",
    "shock",
    "transition",
    "risk_lock",
    "session_lock",
    "validation_fail",
    "user_stream_stale",
)

_STRUCTURAL_REASONS = {
    "total_cap_reached",
    "directional_cap_reached",
    "cluster_cap_reached",
    "thesis_duplicate_blocked",
    "thesis_active_cap_reached",
    "thesis_cluster_cap_zero_risk",
}

_ROLLOUT_REASONS = {
    "mode_shadow_only",
    "mode_daily_trade_limit_reached",
    "mode_total_risk_cap_reached",
    "live_disabled_family",
    "execution_mode_cap_exceeded",
    "live_limit_only_entry_required",
    "live_entry_model_not_allowed",
    "micro_live_strategy_hour_not_allowed",
    "micro_live_strategy_time_bucket_not_allowed",
    "micro_live_plan_id_blocklisted",
    "micro_live_session_not_allowed",
    "live_family_cluster_window_cap_reached",
    "live_family_loss_cooldown_active",
}

_QUALITY_REASONS = {
    "risk_budget_below_min",
    "adjusted_score_non_positive",
    "invalid_candidate",
    "sizing_zero_risk",
}

_HARD_GATE_GROUPS = {"safety", "structural"}
_SOFTENING_GATE_GROUPS = {"quality"}
_RECONCILIATION_ACTIVE_WINDOW_HOURS = 24
_ACTIVE_CONTRACT_REPLAY_BASELINE_FILE = "strategy_proof_contract_live_subset.json"


class ExecutionOperatorDashboardService:
    def __init__(
        self,
        *,
        intent_repo: OrderIntentRepository,
        submission_repo: OrderSubmissionRepository,
        reconciliation_repo: ExecutionReconciliationEventRepository,
        position_repo: BinancePositionRepository,
        settings: Settings | None = None,
    ):
        self.intent_repo = intent_repo
        self.submission_repo = submission_repo
        self.reconciliation_repo = reconciliation_repo
        self.position_repo = position_repo
        self.settings = settings or get_settings()

    def _execution_mode_value(self) -> str:
        mode = self.settings.auto_trading_execution_mode
        return str(getattr(mode, "value", mode))

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return bool(default)

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
        for key, action in (
            ("entry_timing_target", "run_entry_timing_split_review"),
            ("execution_style_target", "run_execution_style_split_review"),
        ):
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
    def _gate_group_for_reason(reason: str | None) -> str:
        normalized = str(reason or "").strip().lower()
        if not normalized:
            return "unknown"
        if normalized.startswith(_SAFETY_REASON_PREFIXES):
            return "safety"
        if normalized in _STRUCTURAL_REASONS:
            return "structural"
        if normalized in _ROLLOUT_REASONS:
            return "rollout"
        if normalized in _QUALITY_REASONS:
            return "quality"
        return "unknown"

    def _gate_group_rows(
        self,
        blocked_rows: list[dict[str, Any]],
        *,
        runtime_candidates: int,
    ) -> tuple[dict[str, int], list[dict[str, Any]]]:
        counts: dict[str, int] = {}
        for row in blocked_rows:
            group = self._gate_group_for_reason(row.get("block_reason"))
            counts[group] = counts.get(group, 0) + 1

        rows = []
        for key, value in counts.items():
            share = round((value / runtime_candidates), 4) if runtime_candidates > 0 else 0.0
            rows.append(
                {
                    "key": key,
                    "blocked": int(value),
                    "share_of_runtime_candidates": share,
                }
            )
        rows.sort(key=lambda item: (-item["blocked"], item["key"]))
        return counts, rows

    @staticmethod
    def _row_session_name(row: dict[str, Any]) -> str:
        return row_session_name(row)

    @staticmethod
    def _row_matches_contract_filters(row: dict[str, Any], filters: dict[str, Any] | None) -> bool:
        payload = dict(row or {})
        filter_payload = dict(filters or {})
        symbol = str(filter_payload.get("symbol") or "").strip().upper()
        execution_mode = str(filter_payload.get("execution_mode") or "").strip().upper()
        strategy_families = {
            str(item or "").strip().lower()
            for item in list(filter_payload.get("strategy_families") or [])
            if str(item or "").strip()
        }
        entry_models = {
            str(item or "").strip().upper()
            for item in list(filter_payload.get("entry_models") or [])
            if str(item or "").strip()
        }
        directions = {
            str(item or "").strip().upper()
            for item in list(filter_payload.get("directions") or [])
            if str(item or "").strip()
        }
        sessions = {
            str(item or "").strip().lower()
            for item in list(filter_payload.get("sessions") or [])
            if str(item or "").strip()
        }
        row_symbol = str(payload.get("symbol") or "").strip().upper()
        row_execution_mode = str(payload.get("execution_mode") or "").strip().upper()
        family = str(payload.get("strategy_family") or dict(payload.get("validity") or {}).get("strategy_family") or "").lower()
        entry_model = str(payload.get("entry_model") or dict(payload.get("validity") or {}).get("entry_model") or "").upper()
        direction = str(payload.get("direction") or dict(payload.get("validity") or {}).get("direction") or "").upper()
        if symbol and row_symbol and row_symbol != symbol:
            return False
        if execution_mode and row_execution_mode and row_execution_mode != execution_mode:
            return False
        if strategy_families and family not in strategy_families:
            return False
        if entry_models and entry_model not in entry_models:
            return False
        if directions and direction not in directions:
            return False
        if sessions and ExecutionOperatorDashboardService._row_session_name(payload) not in sessions:
            return False
        return True

    def _gate_group_reason_summary(
        self,
        blocked_rows: list[dict[str, Any]],
        *,
        groups: set[str],
        runtime_candidates: int,
        current_reason: str | None = None,
    ) -> dict[str, Any]:
        reason_counts: dict[str, int] = {}
        total_blocked = 0
        for row in blocked_rows:
            reason = str(row.get("block_reason") or "").strip()
            group = self._gate_group_for_reason(reason)
            if group not in groups:
                continue
            total_blocked += 1
            key = reason or "unknown"
            reason_counts[key] = reason_counts.get(key, 0) + 1

        current_reason_normalized = str(current_reason or "").strip()
        current_group = self._gate_group_for_reason(current_reason_normalized)
        current_reason_priority = False
        if current_reason_normalized and current_group in groups:
            total_blocked += 1
            reason_counts[current_reason_normalized] = reason_counts.get(current_reason_normalized, 0) + 1
            current_reason_priority = True

        top_reason = None
        top_reason_count = 0
        if reason_counts:
            top_reason, top_reason_count = max(
                reason_counts.items(),
                key=lambda item: (
                    item[1],
                    1 if current_reason_priority and item[0] == current_reason_normalized else 0,
                    item[0],
                ),
            )

        return {
            "blocked": total_blocked,
            "share_of_runtime_candidates": round((total_blocked / runtime_candidates), 4)
            if runtime_candidates > 0
            else 0.0,
            "top_reason": top_reason,
            "top_reason_count": top_reason_count,
            "reason_counts": reason_counts,
        }

    @staticmethod
    def _candidate_pass_rates(
        accepted_rows: list[dict[str, Any]],
        blocked_rows: list[dict[str, Any]],
        *,
        key_fn,
    ) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}

        def _get_bucket(key: str) -> dict[str, Any]:
            bucket = buckets.get(key)
            if bucket is None:
                bucket = {
                    "key": key,
                    "candidates": 0,
                    "accepted": 0,
                    "blocked": 0,
                    "ev_sum": 0.0,
                    "ev_count": 0,
                    "win_sum": 0.0,
                    "win_count": 0,
                    "risk_sum": 0.0,
                    "risk_count": 0,
                }
                buckets[key] = bucket
            return bucket

        def _accumulate(row: dict[str, Any], *, accepted: bool) -> None:
            raw_key = key_fn(row)
            key = str(raw_key or "unknown")
            bucket = _get_bucket(key)
            bucket["candidates"] += 1
            if accepted:
                bucket["accepted"] += 1
            else:
                bucket["blocked"] += 1

            ev_value = row.get("expected_ev_r")
            if isinstance(ev_value, (int, float)):
                bucket["ev_sum"] += float(ev_value)
                bucket["ev_count"] += 1

            win_value = row.get("expected_win_prob")
            if isinstance(win_value, (int, float)):
                bucket["win_sum"] += float(win_value)
                bucket["win_count"] += 1

            risk_value = row.get("recommended_risk_r")
            if isinstance(risk_value, (int, float)):
                bucket["risk_sum"] += float(risk_value)
                bucket["risk_count"] += 1

        for row in accepted_rows:
            _accumulate(row, accepted=True)
        for row in blocked_rows:
            _accumulate(row, accepted=False)

        def _finalize(bucket: dict[str, Any]) -> dict[str, Any]:
            candidates = int(bucket["candidates"] or 0)
            accepted = int(bucket["accepted"] or 0)
            blocked = int(bucket["blocked"] or 0)
            pass_rate = round((accepted / candidates), 4) if candidates > 0 else 0.0
            avg_expected_ev_r = round(bucket["ev_sum"] / bucket["ev_count"], 4) if bucket["ev_count"] > 0 else 0.0
            avg_expected_win_prob = round(bucket["win_sum"] / bucket["win_count"], 4) if bucket["win_count"] > 0 else 0.0
            avg_recommended_risk_r = round(bucket["risk_sum"] / bucket["risk_count"], 4) if bucket["risk_count"] > 0 else 0.0
            return {
                "key": bucket["key"],
                "candidates": candidates,
                "accepted": accepted,
                "blocked": blocked,
                "pass_rate": pass_rate,
                "avg_expected_ev_r": avg_expected_ev_r,
                "avg_expected_win_prob": avg_expected_win_prob,
                "avg_recommended_risk_r": avg_recommended_risk_r,
            }

        rows = [_finalize(bucket) for bucket in buckets.values()]
        rows.sort(key=lambda item: (-item["candidates"], -item["pass_rate"], item["key"]))
        return rows

    @staticmethod
    def _pass_rate_bottlenecks(
        rows: list[dict[str, Any]],
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        filtered = [row for row in rows if int(row.get("candidates") or 0) > 0]
        filtered.sort(
            key=lambda item: (
                float(item.get("pass_rate") or 0.0),
                -int(item.get("candidates") or 0),
                item.get("key") or "",
            )
        )
        return filtered[:limit]

    @staticmethod
    def _quality_softening_priorities(
        blocked_rows: list[dict[str, Any]],
        *,
        runtime_candidates: int,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}

        def _count_bucket(counter: dict[str, int], key: str) -> None:
            counter[key] = counter.get(key, 0) + 1

        for row in blocked_rows:
            reason = str(row.get("block_reason") or "").strip()
            if ExecutionOperatorDashboardService._gate_group_for_reason(reason) not in _SOFTENING_GATE_GROUPS:
                continue

            bucket = grouped.get(reason)
            if bucket is None:
                bucket = {
                    "reason": reason or "unknown",
                    "blocked": 0,
                    "family_counts": {},
                    "regime_counts": {},
                    "session_counts": {},
                    "ev_sum": 0.0,
                    "ev_count": 0,
                    "win_sum": 0.0,
                    "win_count": 0,
                }
                grouped[reason] = bucket

            bucket["blocked"] += 1
            _count_bucket(
                bucket["family_counts"],
                str(row.get("strategy_family") or "unknown"),
            )
            _count_bucket(
                bucket["regime_counts"],
                str(row.get("regime") or "unknown"),
            )
            session_state = ((row.get("session_guidance") or {}).get("state")) or "unknown"
            _count_bucket(bucket["session_counts"], str(session_state))

            ev_value = row.get("expected_ev_r")
            if isinstance(ev_value, (int, float)):
                bucket["ev_sum"] += float(ev_value)
                bucket["ev_count"] += 1

            win_value = row.get("expected_win_prob")
            if isinstance(win_value, (int, float)):
                bucket["win_sum"] += float(win_value)
                bucket["win_count"] += 1

        def _top_key(counter: dict[str, int]) -> str:
            if not counter:
                return "unknown"
            return max(counter.items(), key=lambda item: (item[1], item[0]))[0]

        rows: list[dict[str, Any]] = []
        for bucket in grouped.values():
            blocked = int(bucket["blocked"] or 0)
            rows.append(
                {
                    "reason": bucket["reason"],
                    "blocked": blocked,
                    "share_of_runtime_candidates": round((blocked / runtime_candidates), 4)
                    if runtime_candidates > 0
                    else 0.0,
                    "top_family": _top_key(bucket["family_counts"]),
                    "top_regime": _top_key(bucket["regime_counts"]),
                    "top_session": _top_key(bucket["session_counts"]),
                    "avg_expected_ev_r": round(bucket["ev_sum"] / bucket["ev_count"], 4)
                    if bucket["ev_count"] > 0
                    else 0.0,
                    "avg_expected_win_prob": round(bucket["win_sum"] / bucket["win_count"], 4)
                    if bucket["win_count"] > 0
                    else 0.0,
                }
            )
        rows.sort(
            key=lambda item: (
                -int(item["blocked"]),
                -float(item["avg_expected_ev_r"]),
                item["reason"],
            )
        )
        return rows[:limit]

    @staticmethod
    def _alpha_research_summary(
        blocked_rows: list[dict[str, Any]],
        *,
        runtime_candidates: int,
    ) -> dict[str, Any]:
        alpha_rows = [row for row in blocked_rows if ExecutionOperatorDashboardService._safe_bool(row.get("alpha_research_candidate"))]
        if not alpha_rows:
            return {
                "candidates": 0,
                "share_of_runtime_candidates": 0.0,
                "top_reason": None,
                "top_reason_count": 0,
                "reason_counts": {},
            }

        reason_counts: dict[str, int] = {}
        for row in alpha_rows:
            reason = str(row.get("alpha_research_reason") or row.get("block_reason") or "unknown")
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        top_reason, top_reason_count = max(reason_counts.items(), key=lambda item: (item[1], item[0]))
        return {
            "candidates": len(alpha_rows),
            "share_of_runtime_candidates": round((len(alpha_rows) / runtime_candidates), 4)
            if runtime_candidates > 0
            else 0.0,
            "top_reason": top_reason,
            "top_reason_count": top_reason_count,
            "reason_counts": reason_counts,
        }

    @staticmethod
    def _alpha_research_focus_alignment(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        alignment = dict((payload.get("research_focus_alignment") or {}))
        summary = dict((payload.get("summary") or {}))
        if not alignment:
            return {
                "available": False,
                "analysis_symbol": payload.get("analysis_symbol"),
                "aligned_candidate_count": 0,
                "top_focus": None,
                "top_bucket": None,
                "focus_items": [],
                "alpha_research_candidate_count": int(summary.get("alpha_research_candidate_count", 0)),
            }
        return {
            "available": ExecutionOperatorDashboardService._safe_bool(alignment.get("available", False)),
            "analysis_symbol": alignment.get("analysis_symbol") or payload.get("analysis_symbol"),
            "aligned_candidate_count": int(alignment.get("aligned_candidate_count", 0)),
            "top_focus": alignment.get("top_focus"),
            "top_bucket": alignment.get("top_bucket"),
            "focus_items": list(alignment.get("focus_items") or [])[:5],
            "alpha_research_candidate_count": int(summary.get("alpha_research_candidate_count", 0)),
        }

    @staticmethod
    def _alpha_research_recommended_action(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        summary = dict((payload.get("recommended_action_summary") or {}))
        actions = list(payload.get("recommended_actions") or [])
        if not summary and not actions:
            return {
                "available": False,
                "analysis_symbol": payload.get("analysis_symbol"),
                "recommended_action": None,
                "recommended_scope": None,
                "recommended_reason": None,
                "shadow_experiment_type": None,
                "bucket": None,
                "focus": None,
                "confidence": None,
                "sample_note": None,
                "aligned_candidates": 0,
                "deferred_by_experiment_sequence": False,
                "experiment_sequence_state": None,
                "current_priority_experiment": None,
                "current_priority_action": None,
                "exit_optimization_allowed": False,
                "sequencing_reason": None,
                "recommended_actions": [],
            }
        return {
            "available": True,
            "analysis_symbol": summary.get("analysis_symbol") or payload.get("analysis_symbol"),
            "recommended_action": summary.get("recommended_action"),
            "recommended_scope": summary.get("recommended_scope"),
            "recommended_reason": summary.get("recommended_reason"),
            "shadow_experiment_type": summary.get("shadow_experiment_type"),
            "bucket": summary.get("bucket"),
            "focus": summary.get("focus"),
            "confidence": summary.get("confidence"),
            "sample_note": summary.get("sample_note"),
            "aligned_candidates": int(summary.get("aligned_candidates", 0) or 0),
            "deferred_by_experiment_sequence": ExecutionOperatorDashboardService._safe_bool(
                summary.get("deferred_by_experiment_sequence", False)
            ),
            "experiment_sequence_state": summary.get("experiment_sequence_state"),
            "current_priority_experiment": summary.get("current_priority_experiment"),
            "current_priority_action": summary.get("current_priority_action"),
            "exit_optimization_allowed": ExecutionOperatorDashboardService._safe_bool(
                summary.get("exit_optimization_allowed", False)
            ),
            "sequencing_reason": summary.get("sequencing_reason"),
            "recommended_actions": actions[:3],
        }

    @staticmethod
    def _alpha_research_top_shadow_experiment(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        top = dict((payload.get("top_shadow_experiment") or {}))
        templates = list(payload.get("shadow_experiment_templates") or [])
        if not top and not templates:
            return {
                "available": False,
                "analysis_symbol": payload.get("analysis_symbol"),
                "experiment_id": None,
                "title": None,
                "objective": None,
                "recommended_action": None,
                "recommended_scope": None,
                "shadow_experiment_type": None,
                "target": None,
                "focus": None,
                "bucket": None,
                "confidence": None,
                "sample_note": None,
                "deferred_by_experiment_sequence": False,
                "experiment_sequence_state": None,
                "current_priority_experiment": None,
                "current_priority_action": None,
                "exit_optimization_allowed": False,
                "sequencing_reason": None,
                "observe_metrics": [],
                "success_criteria": [],
                "stop_conditions": [],
                "promotion_guardrails": [],
                "shadow_experiment_templates": [],
            }
        return {
            "available": True,
            "analysis_symbol": top.get("analysis_symbol") or payload.get("analysis_symbol"),
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
            "deferred_by_experiment_sequence": ExecutionOperatorDashboardService._safe_bool(
                top.get("deferred_by_experiment_sequence", False)
            ),
            "experiment_sequence_state": top.get("experiment_sequence_state"),
            "current_priority_experiment": top.get("current_priority_experiment"),
            "current_priority_action": top.get("current_priority_action"),
            "exit_optimization_allowed": ExecutionOperatorDashboardService._safe_bool(
                top.get("exit_optimization_allowed", False)
            ),
            "sequencing_reason": top.get("sequencing_reason"),
            "observe_metrics": list(top.get("observe_metrics") or []),
            "success_criteria": list(top.get("success_criteria") or []),
            "stop_conditions": list(top.get("stop_conditions") or []),
            "promotion_guardrails": list(top.get("promotion_guardrails") or []),
            "shadow_experiment_templates": templates[:3],
        }

    @staticmethod
    def _alpha_research_evidence_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        evidence = dict(payload.get("alpha_research_evidence_summary") or {})
        reason_summary = dict(evidence.get("near_miss_reason_summary") or {})
        focus_summary = dict(evidence.get("focus_alignment_summary") or {})
        outcome_summary = dict(evidence.get("outcome_alignment_summary") or {})
        suspects = list(evidence.get("false_negative_suspects") or [])
        if not evidence:
            return {
                "available": False,
                "analysis_symbol": payload.get("analysis_symbol"),
                "top_reason": None,
                "aligned_candidate_count": 0,
                "top_focus": None,
                "top_bucket": None,
                "top_family_bottleneck": None,
                "top_regime_bottleneck": None,
                "top_session_bottleneck": None,
                "suspect_count": 0,
                "top_suspect": None,
        }
        return {
            "available": ExecutionOperatorDashboardService._safe_bool(evidence.get("available", False)),
            "analysis_symbol": evidence.get("analysis_symbol") or payload.get("analysis_symbol"),
            "top_reason": reason_summary.get("top_reason"),
            "aligned_candidate_count": int(focus_summary.get("aligned_candidate_count", 0) or 0),
            "top_focus": focus_summary.get("top_focus"),
            "top_bucket": focus_summary.get("top_bucket"),
            "top_family_bottleneck": dict(outcome_summary.get("top_family_bottleneck") or {}).get("key"),
            "top_regime_bottleneck": dict(outcome_summary.get("top_regime_bottleneck") or {}).get("key"),
            "top_session_bottleneck": dict(outcome_summary.get("top_session_bottleneck") or {}).get("key"),
            "suspect_count": len(suspects),
            "top_suspect": dict((suspects[:1] or [{}])[0]),
        }

    @staticmethod
    def _alpha_research_softening_review(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        review = dict(payload.get("softening_candidate_review") or {})
        if not review:
            return {
                "available": False,
                "top_candidate": None,
                "review_items": [],
        }
        return {
            "available": ExecutionOperatorDashboardService._safe_bool(review.get("available", False)),
            "top_candidate": dict(review.get("top_candidate") or {}),
            "review_items": list(review.get("review_items") or [])[:3],
        }

    @staticmethod
    def _alpha_research_promotion_watchlist(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        watchlist = dict(payload.get("promotion_watchlist") or {})
        if not watchlist:
            return {
                "available": False,
                "watchlist_count": 0,
                "top_watch": None,
                "watch_items": [],
            }
        items = list(watchlist.get("watch_items") or [])
        return {
            "available": ExecutionOperatorDashboardService._safe_bool(watchlist.get("available", False)),
            "watchlist_count": int(watchlist.get("watchlist_count", 0) or 0),
            "top_watch": dict((items[:1] or [{}])[0]),
            "watch_items": items[:3],
        }

    @staticmethod
    def _intent_row(row: Any) -> dict[str, Any]:
        approval_snapshot = dict(row.approval_snapshot or {})
        payload = dict(row.payload or {})
        executable_plan = dict(payload.get("executable_plan") or {})
        return {
            "intent_id": row.intent_id,
            "plan_id": row.plan_id,
            "symbol": row.symbol,
            "strategy_family": row.strategy_family,
            "direction": str(executable_plan.get("direction") or payload.get("direction") or ""),
            "entry_type": str(executable_plan.get("entry_type") or ""),
            "entry_model": str(executable_plan.get("entry_model") or ""),
            "execution_mode": row.execution_mode,
            "approval_state": row.approval_state,
            "submit_decision": row.submit_decision,
            "decision_reason_code": row.decision_reason_code,
            "decision_reason_message": row.decision_reason_message,
            "allowed_execution_mode": approval_snapshot.get("allowed_execution_mode"),
            "deployment_go_no_go": approval_snapshot.get("deployment_go_no_go", ""),
            "deployment_code": approval_snapshot.get("deployment_code", ""),
            "playbook_go_no_go": approval_snapshot.get("playbook_go_no_go", ""),
            "playbook_code": approval_snapshot.get("playbook_code", ""),
            "playbook_action": approval_snapshot.get("playbook_action", ""),
            "outcome_approval_penalty": dict(approval_snapshot.get("outcome_approval_penalty") or {}),
            "thesis_cluster_id": payload.get("thesis_cluster_id", ""),
            "session_guidance": dict(getattr(row, "session_guidance", {}) or payload.get("session_guidance") or {}),
            "created_at": row.created_at,
        }

    @staticmethod
    def _submission_row(row: Any) -> dict[str, Any]:
        return {
            "submission_id": row.submission_id,
            "intent_id": row.intent_id,
            "plan_id": row.plan_id,
            "symbol": row.symbol,
            "state": row.state,
            "submit_status": row.submit_status,
            "message": row.message,
            "adapter": row.adapter,
            "execution_mode": row.execution_mode,
            "client_order_id": row.client_order_id,
            "exchange_order_id": row.exchange_order_id,
            "requested_live": ExecutionOperatorDashboardService._safe_bool(row.requested_live),
            "submitted_at": row.submitted_at,
            "acknowledged_at": row.acknowledged_at,
            "cancelled_at": row.cancelled_at,
        }

    @staticmethod
    def _position_row(row: Any) -> dict[str, Any]:
        return {
            "position_key": row.position_key,
            "symbol": row.symbol,
            "position_side": row.position_side,
            "position_amt": float(row.position_amt),
            "entry_price": float(row.entry_price),
            "mark_price": float(row.mark_price),
            "unrealized_pnl": float(row.unrealized_pnl),
            "notional": float(row.notional),
            "leverage": int(row.leverage),
            "margin_type": row.margin_type,
            "update_ts": row.update_ts,
        }

    @staticmethod
    def _reconciliation_row(row: Any) -> dict[str, Any]:
        severity = str(row.severity or "INFO").upper()
        normalized = "CRITICAL" if severity == "CRITICAL" else ("WARNING" if severity in {"LOW", "MEDIUM", "HIGH", "WARNING"} else "INFO")
        return {
            "event_id": row.event_id,
            "symbol": row.symbol,
            "mismatch_type": row.mismatch_type,
            "severity": normalized,
            "message": row.message,
            "lock_required": ExecutionOperatorDashboardService._safe_bool(row.lock_required),
            "lock_applied": ExecutionOperatorDashboardService._safe_bool(row.lock_applied),
            "lock_scope": row.lock_scope,
            "created_at": row.created_at,
        }

    @staticmethod
    def _as_utc_datetime(value: Any) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _reconciliation_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
        if not events:
            return {
                "healthy": True,
                "highest_severity": "INFO",
                "degraded": False,
                "critical_count": 0,
                "lock_required_count": 0,
                "active_event_count": 0,
                "stale_event_count": 0,
                "latest_event_at": None,
                "latest_event_age_hours": None,
                "stale_highest_severity": "INFO",
                "active_window_hours": _RECONCILIATION_ACTIVE_WINDOW_HOURS,
            }

        now = datetime.now(timezone.utc)
        active_cutoff = now - timedelta(hours=_RECONCILIATION_ACTIVE_WINDOW_HOURS)
        latest_event_at: datetime | None = None
        active_events: list[dict[str, Any]] = []
        stale_events: list[dict[str, Any]] = []

        for item in events:
            created_at = ExecutionOperatorDashboardService._as_utc_datetime(item.get("created_at"))
            if created_at is not None and (latest_event_at is None or created_at > latest_event_at):
                latest_event_at = created_at
            if created_at is None or created_at >= active_cutoff:
                active_events.append(item)
            else:
                stale_events.append(item)

        if not active_events:
            stale_highest = max(
                stale_events,
                key=lambda item: _SEVERITY_ORDER.get(str(item.get("severity") or "INFO"), 0),
                default={},
            )
            return {
                "healthy": True,
                "highest_severity": "INFO",
                "degraded": False,
                "critical_count": 0,
                "lock_required_count": 0,
                "active_event_count": 0,
                "stale_event_count": len(stale_events),
                "latest_event_at": latest_event_at,
                "latest_event_age_hours": round(
                    max((now - latest_event_at).total_seconds(), 0.0) / 3600.0,
                    2,
                )
                if latest_event_at is not None
                else None,
                "stale_highest_severity": str(stale_highest.get("severity") or "INFO"),
                "active_window_hours": _RECONCILIATION_ACTIVE_WINDOW_HOURS,
            }

        highest = max(active_events, key=lambda item: _SEVERITY_ORDER.get(str(item.get("severity") or "INFO"), 0))
        highest_severity = str(highest.get("severity") or "INFO")
        critical_count = sum(1 for item in active_events if str(item.get("severity") or "") == "CRITICAL")
        lock_required_count = sum(
            1 for item in active_events if ExecutionOperatorDashboardService._safe_bool(item.get("lock_required"))
        )
        degraded = _SEVERITY_ORDER.get(highest_severity, 0) >= _SEVERITY_ORDER["WARNING"]
        stale_highest = max(
            stale_events,
            key=lambda item: _SEVERITY_ORDER.get(str(item.get("severity") or "INFO"), 0),
            default={},
        )
        return {
            "healthy": not degraded,
            "highest_severity": highest_severity,
            "degraded": degraded,
            "critical_count": critical_count,
            "lock_required_count": lock_required_count,
            "active_event_count": len(active_events),
            "stale_event_count": len(stale_events),
            "latest_event_at": latest_event_at,
            "latest_event_age_hours": round(
                max((now - latest_event_at).total_seconds(), 0.0) / 3600.0,
                2,
            )
            if latest_event_at is not None
            else None,
            "stale_highest_severity": str(stale_highest.get("severity") or "INFO"),
            "active_window_hours": _RECONCILIATION_ACTIVE_WINDOW_HOURS,
        }

    @staticmethod
    def _portfolio_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row or {})
        strategy_sizing = dict(item.get("strategy_sizing") or {})
        runtime_signal_shadow_tilt = dict(
            item.get("runtime_signal_shadow_tilt")
            or strategy_sizing.get("runtime_signal_shadow_tilt")
            or dict(item.get("validity") or {}).get("runtime_signal_shadow_tilt")
            or {}
        )
        return {
            "symbol": item.get("symbol", ""),
            "plan_id": item.get("plan_id", ""),
            "strategy_family": item.get("strategy_family", ""),
            "entry_model": item.get("entry_model", ""),
            "entry_type": item.get("entry_type", ""),
            "direction": item.get("direction", ""),
            "validity": dict(item.get("validity") or {}),
            "strategy_cluster": item.get("strategy_cluster"),
            "strategy_cluster_status": item.get("strategy_cluster_status"),
            "multi_strategy_overlay": dict(item.get("multi_strategy_overlay") or {}),
            "b_continuation_activation": dict(item.get("b_continuation_activation") or {}),
            "strategy_cluster_balance": dict(item.get("strategy_cluster_balance") or {}),
            "regime": item.get("regime", ""),
            "session_guidance": dict(item.get("session_guidance") or {}),
            "recommended_risk_r": float(item.get("recommended_risk_r", 0.0) or 0.0),
            "allocated_risk_r": float(item.get("allocated_risk_r", item.get("recommended_risk_r", 0.0)) or 0.0),
            "block_reason": item.get("block_reason"),
            "outcome_bias": dict(item.get("outcome_bias") or {}),
            "edge_experiment_focus": dict(item.get("edge_experiment_focus") or {}),
            "capital_allocator": dict(item.get("capital_allocator") or {}),
            "capital_pressure": str(item.get("capital_pressure", "neutral") or "neutral"),
            "runtime_signal_shadow_tilt": runtime_signal_shadow_tilt,
            "strategy_sizing": {
                "outcome_risk_adjustment": dict(strategy_sizing.get("outcome_risk_adjustment") or {}),
                "runtime_signal_shadow_tilt": runtime_signal_shadow_tilt,
            },
        }

    @staticmethod
    def _portfolio_summary(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "universe": payload.get("universe", ""),
            "deployment_go_no_go": payload.get("deployment_go_no_go", ""),
            "deployment_code": payload.get("deployment_code", ""),
            "deployment_message": payload.get("deployment_message", ""),
            "playbook_go_no_go": payload.get("playbook_go_no_go", ""),
            "playbook_code": payload.get("playbook_code", ""),
            "playbook_action": payload.get("playbook_action", ""),
            "playbook_message": payload.get("playbook_message", ""),
            "risk_state": payload.get("risk_state", ""),
            "risk_reason": payload.get("risk_reason", ""),
            "accepted_candidate_count": len(payload.get("accepted_candidates") or []),
            "blocked_candidate_count": len(payload.get("blocked_candidates") or []),
            "alpha_research_candidate_count": len(payload.get("alpha_research_candidates") or []),
            "blocked_reason_counts": dict(payload.get("blocked_reason_counts") or {}),
            "multi_strategy_ab_summary": dict(payload.get("multi_strategy_ab_summary") or {}),
            "strategy_cluster_balance_summary": dict(payload.get("strategy_cluster_balance_summary") or {}),
            "capital_allocator_summary": dict(payload.get("capital_allocator_summary") or {}),
            "current_position_count": len(payload.get("current_positions") or []),
            "headroom_by_regime": dict(payload.get("headroom_by_regime") or {}),
            "accepted_candidates": [
                ExecutionOperatorDashboardService._portfolio_candidate_row(row)
                for row in list(payload.get("accepted_candidates") or [])[:5]
            ],
            "blocked_candidates": [
                ExecutionOperatorDashboardService._portfolio_candidate_row(row)
                for row in list(payload.get("blocked_candidates") or [])[:5]
            ],
        }

    @staticmethod
    def _alert_summary(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "overall": dict(payload.get("overall") or {}),
            "retry_queue": dict(payload.get("retry_queue") or {}),
            "latest_validation_alert": dict(payload.get("latest_validation_alert") or {}),
        }

    @staticmethod
    def _execution_quality_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        final_exit_reasons = dict(payload.get("final_exit_reasons") or {})
        terminal_exit_split = {
            "planned_stop_loss": int(final_exit_reasons.get("stop_loss", 0) or 0),
            "time_failure": int(final_exit_reasons.get("time_failure", 0) or 0),
            "information_failure": int(final_exit_reasons.get("information_failure", 0) or 0),
            "manual_flatten": int(final_exit_reasons.get("manual_flatten", 0) or 0),
            "risk_lock_flatten": int(final_exit_reasons.get("risk_lock_flatten", 0) or 0),
            "session_end_flatten": int(final_exit_reasons.get("session_end_flatten", 0) or 0),
            "structure_failure": int(final_exit_reasons.get("structure_failure", 0) or 0),
            "target_tp1": int(final_exit_reasons.get("target_tp1", 0) or 0),
            "target_tp2": int(final_exit_reasons.get("target_tp2", 0) or 0),
            "target_tp3": int(final_exit_reasons.get("target_tp3", 0) or 0),
        }
        operational_forced_exit_split = {
            "time_failure": terminal_exit_split["time_failure"],
            "information_failure": terminal_exit_split["information_failure"],
            "manual_flatten": terminal_exit_split["manual_flatten"],
            "risk_lock_flatten": terminal_exit_split["risk_lock_flatten"],
            "session_end_flatten": terminal_exit_split["session_end_flatten"],
        }
        return {
            "symbol": payload.get("symbol", ""),
            "filters": dict(payload.get("filters") or {}) or None,
            "fill_rate": payload.get("fill_rate", 0.0),
            "plan_fill_rate": payload.get("fill_rate", 0.0),
            "plan_fill_rate_denominator": "matured_plans",
            "terminal_exit_ratio": payload.get("forced_exit_ratio", 0.0),
            "terminal_exit_ratio_denominator": "closed_plans",
            "plans_total": int(payload.get("plans_total", 0) or 0),
            "matured_plans": int(payload.get("plans_matured", 0) or 0),
            "filled_matured_plans": int(payload.get("fills_matched", 0) or 0),
            "unfilled_matured_plans": max(
                int(payload.get("plans_matured", 0) or 0) - int(payload.get("fills_matched", 0) or 0),
                0,
            ),
            "fill_events_total": payload.get("fill_events_total", 0),
            "slippage_bps": dict(payload.get("slippage_bps") or {}),
            "fees": dict(payload.get("fees") or {}),
            "unfilled_reasons": dict(payload.get("unfilled_reasons") or {}),
            "unfilled_reason_details": dict(payload.get("unfilled_reason_details") or {}),
            "entry_reach_diagnostics": dict(payload.get("entry_reach_diagnostics") or {}),
            "target_exit_ratio": payload.get("target_exit_ratio", 0.0),
            "forced_exit_ratio": payload.get("forced_exit_ratio", 0.0),
            "forced_exit_ratio_total": payload.get("forced_exit_ratio", 0.0),
            "information_failure_ratio": payload.get("information_failure_ratio", 0.0),
            "time_failure_ratio": payload.get("time_failure_ratio", 0.0),
            "final_exit_reasons": dict(payload.get("final_exit_reasons") or {}),
            "terminal_exit_split": terminal_exit_split,
            "operational_forced_exit_split": operational_forced_exit_split,
            "operational_forced_exit_count": int(sum(operational_forced_exit_split.values())),
            "operational_forced_exit_ratio": (
                float(sum(operational_forced_exit_split.values())) / float(sum(final_exit_reasons.values()))
                if sum(final_exit_reasons.values()) > 0
                else 0.0
            ),
            "operational_forced_exit_ratio_denominator": "closed_plans",
            "report_path": payload.get("report_path"),
        }

    @staticmethod
    def _score_to_outcome_funnel_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        snapshot = dict(payload.get("snapshot_selection") or {})
        history = dict(payload.get("historical_execution_outcomes") or {})
        decomposition = dict(payload.get("decomposition") or {})
        money_funnel = dict(payload.get("money_funnel") or {})
        operating_kpis = build_outcome_funnel_operating_kpis(payload)
        return {
            "available": ExecutionOperatorDashboardService._safe_bool(payload.get("available", False)),
            "reason": payload.get("reason", "not_available"),
            "report_window_days": int(payload.get("report_window_days", 0) or 0),
            "filters": dict(payload.get("filters") or {}) or None,
            "coverage_note": payload.get("coverage_note"),
            "runtime_candidates": int(snapshot.get("runtime_candidates", 0) or 0),
            "accepted_candidates": int(snapshot.get("accepted_candidates", 0) or 0),
            "blocked_candidates": int(snapshot.get("blocked_candidates", 0) or 0),
            "accept_rate": float(snapshot.get("accept_rate", 0.0) or 0.0),
            "submitted": int(history.get("submitted", 0) or 0),
            "filled": int(history.get("filled", 0) or 0),
            "closed": int(history.get("closed", 0) or 0),
            "profitable": int(history.get("profitable", 0) or 0),
            "baseline_cost_profitable": int(history.get("baseline_cost_profitable", 0) or 0),
            "fill_rate_from_submitted": float(history.get("fill_rate_from_submitted", 0.0) or 0.0),
            "submitted_to_fill_rate": float(history.get("fill_rate_from_submitted", 0.0) or 0.0),
            "submitted_to_fill_rate_denominator": "submitted_plans",
            "close_rate_from_filled": float(history.get("close_rate_from_filled", 0.0) or 0.0),
            "profitable_rate_from_closed": float(history.get("profitable_rate_from_closed", 0.0) or 0.0),
            "baseline_cost_profitable_rate_from_closed": float(
                history.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0
            ),
            "money_funnel": money_funnel if money_funnel else None,
            "operating_kpis": operating_kpis,
            "top_family_bucket": dict((list(decomposition.get("family") or [])[:1] or [{}])[0]),
            "top_regime_bucket": dict((list(decomposition.get("regime") or [])[:1] or [{}])[0]),
            "top_session_bucket": dict((list(decomposition.get("session") or [])[:1] or [{}])[0]),
            "top_entry_model_bucket": dict((list(decomposition.get("entry_model") or [])[:1] or [{}])[0]),
            "top_entry_timing_bucket": dict((list(decomposition.get("entry_timing_variant") or [])[:1] or [{}])[0]),
            "top_execution_mode_bucket": dict((list(decomposition.get("execution_mode") or [])[:1] or [{}])[0]),
            "top_execution_style_bucket": dict((list(decomposition.get("execution_style") or [])[:1] or [{}])[0]),
        }

    @classmethod
    def _active_contract_summary(cls, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        return {
            "filters": dict(payload.get("filters") or {}) or None,
            "raw_counts": dict(payload.get("raw_counts") or {}) or None,
            "recent_intent_summary": dict(payload.get("recent_intent_summary") or {}) or None,
            "flow_cadence": dict(payload.get("flow_cadence") or {}) or None,
            "replay_flow_baseline": dict(payload.get("replay_flow_baseline") or {}) or None,
            "promotion_shadow_counter": dict(payload.get("promotion_shadow_counter") or {}) or None,
            "shadow_relaxation_priority": dict(payload.get("shadow_relaxation_priority") or {}) or None,
            "transition_edge_variant_shadow": dict(payload.get("transition_edge_variant_shadow") or {}) or None,
            "selection_shortfall_breakdown": dict(payload.get("selection_shortfall_breakdown") or {}) or None,
            "execution_quality_summary": cls._execution_quality_summary(
                dict(payload.get("execution_quality_summary") or {}) or None
            ),
            "score_to_outcome_funnel": cls._score_to_outcome_funnel_summary(
                dict(payload.get("score_to_outcome_funnel_summary") or {}) or None
            ),
            "opportunity_capture": dict(payload.get("opportunity_capture_summary") or {}) or None,
        }

    @staticmethod
    def _active_contract_flow_cadence(
        *,
        recent_intents: list[dict[str, Any]],
        days: int,
        score_to_outcome_funnel_summary: dict[str, Any] | None,
    ) -> dict[str, Any]:
        last_created_at = None
        for row in recent_intents:
            created_at = ExecutionOperatorDashboardService._as_utc_datetime(row.get("created_at"))
            if created_at is None:
                continue
            if last_created_at is None or created_at > last_created_at:
                last_created_at = created_at
        now = datetime.now(timezone.utc)
        hours_since_last_active_contract_intent = (
            round(max((now - last_created_at).total_seconds(), 0.0) / 3600.0, 2)
            if last_created_at is not None
            else None
        )
        funnel = dict(score_to_outcome_funnel_summary or {})
        history = dict(funnel.get("historical_execution_outcomes") or {})
        snapshot = dict(funnel.get("snapshot_selection") or {})
        runtime_candidates = int(snapshot.get("runtime_candidates", 0) or 0)
        submitted = int(history.get("submitted", 0) or 0)
        closed = int(history.get("closed", 0) or 0)
        cadence_window_days = max(int(days or 1), 1)
        execution_sample_window_days = max(int(funnel.get("report_window_days", 0) or cadence_window_days), 1)
        current_window_active_contract_intents_per_week = round((len(recent_intents) / cadence_window_days) * 7.0, 4)
        execution_sample_submitted_per_week = round((submitted / execution_sample_window_days) * 7.0, 4)
        execution_sample_closed_per_week = round((closed / execution_sample_window_days) * 7.0, 4)
        if runtime_candidates > 0:
            flow_state = "active_now"
        elif last_created_at is None:
            flow_state = "no_recent_active_contract_flow"
        else:
            flow_state = "currently_sparse"
        return {
            "cadence_window_days": cadence_window_days,
            "cadence_window_basis": "recent_active_contract_intents",
            "execution_sample_window_days": execution_sample_window_days,
            "execution_sample_window_basis": "contract_faithful_execution_sample",
            "hours_since_last_active_contract_intent": hours_since_last_active_contract_intent,
            "runtime_candidates_current_snapshot": runtime_candidates,
            "current_window_active_contract_intent_count": len(recent_intents),
            "current_window_active_contract_intents_per_week": current_window_active_contract_intents_per_week,
            "execution_sample_submitted_count": submitted,
            "execution_sample_closed_count": closed,
            "execution_sample_submitted_per_week": execution_sample_submitted_per_week,
            "execution_sample_closed_per_week": execution_sample_closed_per_week,
            "flow_state": flow_state,
        }

    def _active_contract_replay_flow_baseline(self, *, filters: dict[str, Any], cadence_window: dict[str, Any]) -> dict[str, Any] | None:
        usdt_proxy = usdt_proxy_rows_for_active_contract(self.settings, filters)
        if usdt_proxy is not None:
            replay_window_days = max(float(usdt_proxy.get("days") or 0.0), 1.0)
            replay_window_weeks = replay_window_days / 7.0
            replay_rows = list(usdt_proxy.get("rows") or [])
            expected_active_contract_candidates_per_week = (
                round(len(replay_rows) / replay_window_weeks, 4)
                if replay_window_weeks > 0
                else 0.0
            )
            expected_closed_per_week_from_replay = expected_active_contract_candidates_per_week
            observed_current_window_intents_per_week = float(
                cadence_window.get("current_window_active_contract_intents_per_week") or 0.0
            )
            live_vs_replay_flow_ratio = (
                round(observed_current_window_intents_per_week / expected_active_contract_candidates_per_week, 4)
                if expected_active_contract_candidates_per_week > 0
                else None
            )
            return {
                "available": True,
                "source": str(usdt_proxy.get("source") or "micro_main_usdt_proxy_backtest"),
                "source_path": str(usdt_proxy.get("source_path") or ""),
                "generated_at": str(usdt_proxy.get("generated_at") or ""),
                "replay_window_days": round(replay_window_days, 4),
                "replay_trade_count": len(replay_rows),
                "expected_active_contract_candidates_per_week_from_replay": expected_active_contract_candidates_per_week,
                "expected_closed_per_week_from_replay": expected_closed_per_week_from_replay,
                "observed_current_window_active_contract_intents_per_week_live": observed_current_window_intents_per_week,
                "live_vs_replay_flow_ratio": live_vs_replay_flow_ratio,
                "comparison_only": True,
            }

        cache_path = Path(self.settings.validation_report_dir) / "historical_walk_forward_cache" / _ACTIVE_CONTRACT_REPLAY_BASELINE_FILE
        if not cache_path.exists():
            return None
        try:
            payload = json.loads(cache_path.read_text())
        except Exception:
            return None

        simulation_start_ts = str(payload.get("simulation_start_ts") or "")
        simulation_end_ts = str(payload.get("simulation_end_ts") or "")
        try:
            simulation_start = datetime.fromisoformat(simulation_start_ts.replace("Z", "+00:00"))
            simulation_end = datetime.fromisoformat(simulation_end_ts.replace("Z", "+00:00"))
        except ValueError:
            return None
        if simulation_start.tzinfo is None:
            simulation_start = simulation_start.replace(tzinfo=timezone.utc)
        if simulation_end.tzinfo is None:
            simulation_end = simulation_end.replace(tzinfo=timezone.utc)
        replay_window_days = max((simulation_end - simulation_start).total_seconds() / 86400.0, 1.0)
        replay_window_weeks = replay_window_days / 7.0

        filter_symbol = str(filters.get("symbol") or "").strip().upper()
        strategy_families = {
            str(item or "").strip().lower()
            for item in list(filters.get("strategy_families") or [])
            if str(item or "").strip()
        }
        entry_models = {
            str(item or "").strip().upper()
            for item in list(filters.get("entry_models") or [])
            if str(item or "").strip()
        }
        directions = {
            str(item or "").strip().upper()
            for item in list(filters.get("directions") or [])
            if str(item or "").strip()
        }
        sessions = {
            str(item or "").strip().lower()
            for item in list(filters.get("sessions") or [])
            if str(item or "").strip()
        }

        replay_rows = [
            dict(row)
            for row in list(payload.get("trade_rows") or [])
            if (
                (not filter_symbol or str(row.get("symbol") or "").strip().upper() == filter_symbol)
                and (
                    not strategy_families
                    or str(row.get("strategy_family") or "").strip().lower() in strategy_families
                )
                and (
                    not entry_models
                    or str(row.get("entry_model") or "").strip().upper() in entry_models
                )
                and (
                    not directions
                    or str(row.get("direction") or "").strip().upper() in directions
                )
                and (
                    not sessions
                    or self._row_session_name(dict(row)) in sessions
                )
            )
        ]
        expected_active_contract_candidates_per_week = (
            round(len(replay_rows) / replay_window_weeks, 4)
            if replay_window_weeks > 0
            else 0.0
        )
        expected_closed_per_week_from_replay = round(len(replay_rows) / replay_window_weeks, 4) if replay_window_weeks > 0 else 0.0
        observed_current_window_intents_per_week = float(
            cadence_window.get("current_window_active_contract_intents_per_week") or 0.0
        )
        live_vs_replay_flow_ratio = (
            round(observed_current_window_intents_per_week / expected_active_contract_candidates_per_week, 4)
            if expected_active_contract_candidates_per_week > 0
            else None
        )
        return {
            "available": True,
            "source_path": str(cache_path),
            "replay_window_days": round(replay_window_days, 4),
            "expected_active_contract_candidates_per_week_from_replay": expected_active_contract_candidates_per_week,
            "expected_closed_per_week_from_replay": expected_closed_per_week_from_replay,
            "observed_current_window_active_contract_intents_per_week_live": observed_current_window_intents_per_week,
            "live_vs_replay_flow_ratio": live_vs_replay_flow_ratio,
            "comparison_only": True,
        }

    @staticmethod
    def _execution_degradation_advisory_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        reasons = list(payload.get("reasons") or [])
        return {
            "available": ExecutionOperatorDashboardService._safe_bool(payload.get("available", False)),
            "status": payload.get("status", "healthy"),
            "healthy": ExecutionOperatorDashboardService._safe_bool(payload.get("healthy", True), default=True),
            "summary": payload.get("summary", ""),
            "recommended_action": payload.get("recommended_action", "continue_runtime_monitoring"),
            "reason_codes": list(payload.get("reason_codes") or []),
            "sample_context": dict(payload.get("sample_context") or {}),
            "top_reason": dict((reasons[:1] or [{}])[0]),
        }

    @staticmethod
    def _mode_advisory_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        return {
            "available": ExecutionOperatorDashboardService._safe_bool(payload.get("available", False)),
            "coverage_note": payload.get("coverage_note"),
            "family_top": dict((list(payload.get("family") or [])[:1] or [{}])[0]),
            "regime_top": dict((list(payload.get("regime") or [])[:1] or [{}])[0]),
            "session_top": dict((list(payload.get("session") or [])[:1] or [{}])[0]),
        }

    @staticmethod
    def _family_execution_degradation_advisory_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        families = list(payload.get("families") or [])
        return {
            "available": ExecutionOperatorDashboardService._safe_bool(payload.get("available", False)),
            "coverage_note": payload.get("coverage_note"),
            "family_count": len(families),
            "top_family": dict((families[:1] or [{}])[0]),
            "families": [dict(item) for item in families[:3]],
        }

    @staticmethod
    def _operator_action_priority_summary(
        payload: dict[str, Any] | None,
        *,
        symbol: str = "",
        universe: str = "usdt_reliable_balanced_31",
        days: int = 7,
    ) -> dict[str, Any] | None:
        if not payload:
            return None
        priority = ExecutionOperatorDashboardService._normalize_operator_action_priority_payload(
            payload,
            symbol=symbol,
            universe=universe,
            days=days,
        )
        return {
            "available": ExecutionOperatorDashboardService._safe_bool(priority.get("available", False)),
            "top_action": priority.get("top_action", "continue_runtime_monitoring"),
            "top_reason": priority.get("top_reason", ""),
            "top_action_followup_command": priority.get("top_action_followup_command", ""),
            "priority_level": priority.get("priority_level", "monitor"),
            "priority_source": priority.get("priority_source", "monitor"),
            "action_family": priority.get("action_family", "monitor"),
            "supporting_signals": list(priority.get("supporting_signals") or []),
            "blocking_signals": list(priority.get("blocking_signals") or []),
            "next_actions": [dict(item) for item in list(priority.get("next_actions") or [])[:3]],
            "capture_context": dict(priority.get("capture_context") or {}),
            "experiment_context": dict(priority.get("experiment_context") or {}),
            "experiment_execution_policy": dict(priority.get("experiment_execution_policy") or {}),
            "deferred_experiment_actions": [
                dict(item) for item in list(priority.get("deferred_experiment_actions") or [])[:3]
            ],
            "advisory_only": ExecutionOperatorDashboardService._safe_bool(
                priority.get("advisory_only", True),
                default=True,
            ),
        }

    @staticmethod
    def _approval_strip_summary(
        *,
        portfolio_summary: dict[str, Any] | None,
        operator_action_priority_summary: dict[str, Any] | None,
        safety_state: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        portfolio = dict(portfolio_summary or {})
        priority = dict(operator_action_priority_summary or {})
        safety = dict(safety_state or {})
        if not portfolio and not priority and not safety:
            return None

        deployment_go_no_go = str(portfolio.get("deployment_go_no_go") or "")
        playbook_go_no_go = str(portfolio.get("playbook_go_no_go") or "")
        playbook_action = str(portfolio.get("playbook_action") or "")
        playbook_message = str(portfolio.get("playbook_message") or "")
        deployment_message = str(portfolio.get("deployment_message") or "")
        blocking_reason_code = str(safety.get("blocking_reason_code") or "")
        blocking_reason_message = str(safety.get("blocking_reason_message") or "")
        raw_entries_allowed = safety.get("new_entry_allowed")
        entries_allowed = (
            ExecutionOperatorDashboardService._safe_bool(raw_entries_allowed)
            if raw_entries_allowed is not None
            else None
        )

        primary_reason = (
            blocking_reason_message
            or str(priority.get("top_reason") or "")
            or deployment_message
            or playbook_message
            or "dashboard approval strip unavailable"
        )

        approve_value = "approval usable"
        if entries_allowed is False:
            approve_value = "entry gate blocked"
        elif deployment_go_no_go == "NO_GO":
            approve_value = "runtime no_go"
        elif deployment_go_no_go == "MANUAL_REVIEW":
            approve_value = "manual review first"
        approve_reason = (
            blocking_reason_message
            or deployment_message
            or playbook_message
            or str(priority.get("top_reason") or "")
            or "dashboard runtime approval unavailable"
        )

        if deployment_go_no_go and playbook_go_no_go and deployment_go_no_go != playbook_go_no_go:
            align_value = "playbook_drift"
            align_reason = " | ".join(
                part
                for part in [
                    f"deployment={deployment_go_no_go}",
                    f"playbook={playbook_go_no_go}",
                    deployment_message or playbook_message,
                ]
                if part
            )
        elif entries_allowed is False and playbook_go_no_go == "GO":
            align_value = "entry_gate_drift"
            align_reason = " | ".join(
                part
                for part in [
                    f"blocking_reason={blocking_reason_code}" if blocking_reason_code else "",
                    blocking_reason_message,
                    playbook_message,
                ]
                if part
            ) or "dashboard runtime entry gate is blocked while playbook remains GO"
        elif portfolio or entries_allowed is not None or blocking_reason_code:
            align_value = "aligned"
            align_reason = " | ".join(
                part
                for part in [
                    f"deployment={deployment_go_no_go}" if deployment_go_no_go else "",
                    f"playbook={playbook_go_no_go}" if playbook_go_no_go else "",
                    f"blocking_reason={blocking_reason_code}" if blocking_reason_code else "",
                    blocking_reason_message or deployment_message or playbook_message,
                ]
                if part
            ) or "dashboard runtime approval is aligned"
        else:
            align_value = "not_available"
            align_reason = "dashboard runtime alignment unavailable"

        act_value = str(
            priority.get("top_action")
            or playbook_action
            or ("review_entry_gate_block_before_rollout" if entries_allowed is False else "continue_runtime_monitoring")
        )
        act_reason = str(
            priority.get("top_reason")
            or playbook_message
            or blocking_reason_message
            or deployment_message
            or "dashboard runtime action unavailable"
        )
        if priority.get("priority_level"):
            act_priority_level = str(priority.get("priority_level") or "monitor")
        elif entries_allowed is False or deployment_go_no_go == "NO_GO":
            act_priority_level = "urgent"
        elif deployment_go_no_go == "MANUAL_REVIEW":
            act_priority_level = "watch"
        else:
            act_priority_level = "monitor"

        return {
            "primary_reason": primary_reason,
            "approve_value": approve_value,
            "approve_reason": approve_reason,
            "align_value": align_value,
            "align_reason": align_reason,
            "act_value": act_value,
            "act_reason": act_reason,
            "act_priority_level": act_priority_level,
        }

    def generate(
        self,
        *,
        symbol: str | None,
        days: int,
        intent_limit: int,
        reconcile_limit: int,
        safety_state: dict[str, Any],
        portfolio_summary: dict[str, Any],
        alert_summary: dict[str, Any],
        execution_quality_summary: dict[str, Any] | None,
        active_contract_summary: dict[str, Any] | None = None,
        alpha_research_pipeline_summary: dict[str, Any] | None = None,
        score_to_outcome_funnel_summary: dict[str, Any] | None = None,
        execution_degradation_advisory_summary: dict[str, Any] | None = None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None = None,
        mode_advisory_summary: dict[str, Any] | None = None,
        operator_action_priority_summary: dict[str, Any] | None = None,
        rollout_recommendation_summary: dict[str, Any] | None = None,
        strategy_lifecycle_summary: dict[str, Any] | None = None,
        promotion_governance_summary: dict[str, Any] | None = None,
        promotion_review_queue_summary: dict[str, Any] | None = None,
        promotion_remediation_queue_summary: dict[str, Any] | None = None,
        promotion_clearance_tracker_summary: dict[str, Any] | None = None,
        promotion_reopen_queue_summary: dict[str, Any] | None = None,
        promotion_decision_brief_summary: dict[str, Any] | None = None,
        auto_promotion_rollout_execution_summary: dict[str, Any] | None = None,
        performance_decomposition_summary: dict[str, Any] | None = None,
        execution_friction_measurement_summary: dict[str, Any] | None = None,
        reconciliation_symbols: list[str] | None = None,
        forward_stress_regime_validation_summary: dict[str, Any] | None = None,
        kill_condition_automation_summary: dict[str, Any] | None = None,
        b_continuation_activation_summary: dict[str, Any] | None = None,
        b_continuation_edge_validation_summary: dict[str, Any] | None = None,
        strategy_cluster_balance_summary: dict[str, Any] | None = None,
        a_strategy_post_cost_edge_validation_summary: dict[str, Any] | None = None,
        promotion_lifecycle_history_summary: dict[str, Any] | None = None,
        research_promotion_operating_loop_summary: dict[str, Any] | None = None,
        multi_strategy_ab_summary: dict[str, Any] | None = None,
        positive_evidence_expansion_summary: dict[str, Any] | None = None,
        outcome_bucket_granularity_summary: dict[str, Any] | None = None,
        opportunity_capture_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        recent_intents = [
            self._intent_row(row)
            for row in self.intent_repo.list_recent(symbol=symbol, limit=intent_limit, days=days)
        ]
        active_contract_payload = dict(active_contract_summary or {})
        active_contract_filters = dict(active_contract_payload.get("filters") or {})
        if active_contract_filters:
            active_contract_recent_intents = [
                row
                for row in recent_intents
                if self._row_matches_contract_filters(row, active_contract_filters)
            ]
            active_contract_payload["recent_intent_summary"] = {
                "broad_recent_intent_count": len(recent_intents),
                "active_contract_recent_intent_count": len(active_contract_recent_intents),
                "non_active_contract_recent_intent_count": max(
                    len(recent_intents) - len(active_contract_recent_intents),
                    0,
                ),
            }
            active_contract_payload["flow_cadence"] = self._active_contract_flow_cadence(
                recent_intents=active_contract_recent_intents,
                days=days,
                score_to_outcome_funnel_summary=dict(
                    active_contract_payload.get("score_to_outcome_funnel_summary") or {}
                ),
            )
            active_contract_payload["replay_flow_baseline"] = self._active_contract_replay_flow_baseline(
                filters=active_contract_filters,
                cadence_window=dict(active_contract_payload.get("flow_cadence") or {}),
            )
        open_orders = [
            self._submission_row(row)
            for row in self.submission_repo.list_open(symbol=symbol)
        ]
        open_positions = [
            self._position_row(row)
            for row in self.position_repo.list_open(symbol=symbol)
        ]
        reconciliation_events = [
            self._reconciliation_row(row)
            for row in self.reconciliation_repo.list_recent(
                symbol=symbol,
                symbols=None if symbol else reconciliation_symbols,
                limit=reconcile_limit,
                days=days,
            )
        ]
        portfolio_summary_payload = self._portfolio_summary(portfolio_summary)
        accepted_candidate_rows = list(portfolio_summary.get("accepted_candidates") or [])
        blocked_candidate_rows = list(portfolio_summary.get("blocked_candidates") or [])
        fallback_outcome_control_trace = build_outcome_control_trace(
            execution_degradation_advisory=execution_degradation_advisory_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            mode_advisory=mode_advisory_summary,
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
        )
        runtime_outcome_trace = runtime_outcome_control_trace(
            recent_intents=recent_intents,
            accepted_candidate_rows=accepted_candidate_rows,
            blocked_candidate_rows=blocked_candidate_rows,
            fallback_trace=fallback_outcome_control_trace,
        )
        runtime_outcome_trace_summary = summarize_outcome_control_trace(runtime_outcome_trace)
        if runtime_outcome_trace_summary:
            runtime_outcome_trace_summary["portfolio_bias_distribution"] = dict(
                dict(runtime_outcome_trace or {}).get("portfolio_bias", {}).get("distribution") or {}
            )
        operator_action_priority_payload = self._operator_action_priority_summary(
            operator_action_priority_summary,
            symbol=symbol or "",
            universe=str(portfolio_summary_payload.get("universe") or "usdt_reliable_balanced_31"),
            days=max(int(days), 1),
        )
        outcome_attribution_summary = summarize_outcome_attribution(
            build_outcome_attribution(
                score_to_outcome_funnel=score_to_outcome_funnel_summary,
                performance_decomposition_summary=performance_decomposition_summary,
                execution_friction_measurement=execution_friction_measurement_summary,
            )
        )
        edge_experiment_summary = summarize_edge_experiment_review(
            build_edge_experiment_review(score_to_outcome_funnel=score_to_outcome_funnel_summary)
        )
        review_followup_ledger_summary = summarize_split_review_followup_ledger(
            symbol=symbol or "",
            universe=str(portfolio_summary_payload.get("universe") or "usdt_reliable_balanced_31"),
        )
        edge_evolution_summary = summarize_edge_evolution_rule(
            build_edge_evolution_rule(
                edge_experiment_review=edge_experiment_summary,
                rollout_recommendation=rollout_recommendation_summary,
                strategy_lifecycle=strategy_lifecycle_summary,
                kill_condition_automation=kill_condition_automation_summary,
                review_followup_ledger=review_followup_ledger_summary,
            )
        )
        submit_decision_counts: dict[str, int] = {}
        for item in recent_intents:
            submit_decision = str(item.get("submit_decision") or "")
            if submit_decision:
                submit_decision_counts[submit_decision] = submit_decision_counts.get(submit_decision, 0) + 1
        accepted_candidate_count = int(portfolio_summary_payload.get("accepted_candidate_count") or 0)
        blocked_candidate_count = int(portfolio_summary_payload.get("blocked_candidate_count") or 0)
        runtime_candidate_count = accepted_candidate_count + blocked_candidate_count
        blocked_gate_group_counts, blocked_gate_groups = self._gate_group_rows(
            blocked_candidate_rows,
            runtime_candidates=runtime_candidate_count,
        )
        current_entry_gate_reason = str(safety_state.get("blocking_reason_code") or "")
        hard_block_summary = self._gate_group_reason_summary(
            blocked_candidate_rows,
            groups=_HARD_GATE_GROUPS,
            runtime_candidates=runtime_candidate_count,
            current_reason=current_entry_gate_reason,
        )
        softening_candidate_summary = self._gate_group_reason_summary(
            blocked_candidate_rows,
            groups=_SOFTENING_GATE_GROUPS,
            runtime_candidates=runtime_candidate_count,
            current_reason=current_entry_gate_reason,
        )
        rollout_block_summary = self._gate_group_reason_summary(
            blocked_candidate_rows,
            groups={"rollout"},
            runtime_candidates=runtime_candidate_count,
            current_reason=current_entry_gate_reason,
        )
        family_pass_rates = self._candidate_pass_rates(
            accepted_candidate_rows,
            blocked_candidate_rows,
            key_fn=lambda row: row.get("strategy_family") or "unknown",
        )
        regime_pass_rates = self._candidate_pass_rates(
            accepted_candidate_rows,
            blocked_candidate_rows,
            key_fn=lambda row: row.get("regime") or "unknown",
        )
        session_pass_rates = self._candidate_pass_rates(
            accepted_candidate_rows,
            blocked_candidate_rows,
            key_fn=lambda row: ((row.get("session_guidance") or {}).get("state")) or "unknown",
        )
        signal_funnel = {
            "runtime_candidates": runtime_candidate_count,
            "accepted_candidates": accepted_candidate_count,
            "blocked_candidates": blocked_candidate_count,
            "blocked_reason_counts": dict(portfolio_summary_payload.get("blocked_reason_counts") or {}),
            "blocked_gate_group_counts": blocked_gate_group_counts,
            "blocked_gate_groups": blocked_gate_groups,
            "hard_block_summary": hard_block_summary,
            "softening_candidate_summary": softening_candidate_summary,
            "rollout_block_summary": rollout_block_summary,
            "alpha_research_summary": self._alpha_research_summary(
                blocked_candidate_rows,
                runtime_candidates=runtime_candidate_count,
            ),
            "alpha_research_focus_alignment": self._alpha_research_focus_alignment(alpha_research_pipeline_summary),
            "alpha_research_evidence_summary": self._alpha_research_evidence_summary(alpha_research_pipeline_summary),
            "alpha_research_softening_review": self._alpha_research_softening_review(alpha_research_pipeline_summary),
            "alpha_research_promotion_watchlist": self._alpha_research_promotion_watchlist(alpha_research_pipeline_summary),
            "alpha_research_recommended_action": self._alpha_research_recommended_action(alpha_research_pipeline_summary),
            "alpha_research_top_shadow_experiment": self._alpha_research_top_shadow_experiment(
                alpha_research_pipeline_summary
            ),
            "recent_intents": len(recent_intents),
            "submit_decision_counts": submit_decision_counts,
            "open_orders": len(open_orders),
            "open_positions": len(open_positions),
            "current_entry_gate_group": self._gate_group_for_reason(current_entry_gate_reason),
            "current_entry_gate_reason": str(safety_state.get("blocking_reason_message", "")),
            "family_pass_rates": family_pass_rates,
            "regime_pass_rates": regime_pass_rates,
            "session_pass_rates": session_pass_rates,
            "family_bottlenecks": self._pass_rate_bottlenecks(family_pass_rates),
            "regime_bottlenecks": self._pass_rate_bottlenecks(regime_pass_rates),
            "session_bottlenecks": self._pass_rate_bottlenecks(session_pass_rates),
            "quality_softening_priorities": self._quality_softening_priorities(
                blocked_candidate_rows,
                runtime_candidates=runtime_candidate_count,
            ),
            "score_to_outcome_funnel": self._score_to_outcome_funnel_summary(score_to_outcome_funnel_summary),
            "execution_degradation_advisory": self._execution_degradation_advisory_summary(
                execution_degradation_advisory_summary
            ),
            "family_execution_degradation_advisory": self._family_execution_degradation_advisory_summary(
                family_execution_degradation_advisory_summary
            ),
            "mode_advisory": self._mode_advisory_summary(mode_advisory_summary),
            "operator_action_priority": operator_action_priority_payload,
            "outcome_control_trace": runtime_outcome_trace_summary,
            "outcome_attribution": outcome_attribution_summary,
            "edge_experiment_review": edge_experiment_summary,
            "edge_evolution_rule": edge_evolution_summary,
            "review_followup_ledger": review_followup_ledger_summary,
            "rollout_recommendation": dict(rollout_recommendation_summary or {}) or None,
            "strategy_lifecycle": dict(strategy_lifecycle_summary or {}) or None,
            "promotion_governance": dict(promotion_governance_summary or {}) or None,
            "promotion_review_queue": dict(promotion_review_queue_summary or {}) or None,
            "promotion_remediation_queue": dict(promotion_remediation_queue_summary or {}) or None,
            "promotion_clearance_tracker": dict(promotion_clearance_tracker_summary or {}) or None,
            "promotion_reopen_queue": dict(promotion_reopen_queue_summary or {}) or None,
            "promotion_decision_brief": dict(promotion_decision_brief_summary or {}) or None,
            "auto_promotion_rollout_execution": dict(auto_promotion_rollout_execution_summary or {}) or None,
            "execution_friction_measurement": dict(execution_friction_measurement_summary or {}) or None,
            "forward_stress_regime_validation": dict(forward_stress_regime_validation_summary or {}) or None,
            "kill_condition_automation": dict(kill_condition_automation_summary or {}) or None,
            "b_continuation_activation": dict(b_continuation_activation_summary or {}) or None,
            "b_continuation_edge_validation": dict(b_continuation_edge_validation_summary or {}) or None,
            "strategy_cluster_balance": dict(strategy_cluster_balance_summary or {}) or None,
            "a_strategy_post_cost_edge_validation": dict(a_strategy_post_cost_edge_validation_summary or {}) or None,
            "promotion_lifecycle_history": dict(promotion_lifecycle_history_summary or {}) or None,
            "research_promotion_operating_loop": dict(research_promotion_operating_loop_summary or {}) or None,
            "multi_strategy_ab_expansion": dict(multi_strategy_ab_summary or {}) or None,
            "positive_evidence_expansion": dict(positive_evidence_expansion_summary or {}) or None,
            "outcome_bucket_granularity": dict(outcome_bucket_granularity_summary or {}) or None,
            "opportunity_capture": dict(opportunity_capture_summary or {}) or None,
            "active_contract": self._active_contract_summary(active_contract_payload),
            "capital_allocator": dict(portfolio_summary.get("capital_allocator_summary") or {}) or None,
        }
        approval_strip_summary = self._approval_strip_summary(
            portfolio_summary=portfolio_summary,
            operator_action_priority_summary=operator_action_priority_payload,
            safety_state=safety_state,
        )

        return {
            "generated_at": datetime.now(timezone.utc),
            "symbol": symbol.upper() if symbol else None,
            "report_window_days": max(int(days), 1),
            "execution_mode": self._execution_mode_value(),
            "auto_trading_enabled": self._safe_bool(self.settings.auto_trading_enabled),
            "source_of_truth_hint": "execution_runtime_aggregate",
            "new_entries_allowed": self._safe_bool(safety_state.get("new_entry_allowed", False)),
            "blocking_reason_code": str(safety_state.get("blocking_reason_code", "")),
            "blocking_reason_message": str(safety_state.get("blocking_reason_message", "")),
            "deployment_go_no_go": portfolio_summary.get("deployment_go_no_go", ""),
            "deployment_code": portfolio_summary.get("deployment_code", ""),
            "deployment_message": portfolio_summary.get("deployment_message", ""),
            "playbook_go_no_go": portfolio_summary.get("playbook_go_no_go", ""),
            "playbook_code": portfolio_summary.get("playbook_code", ""),
            "playbook_action": portfolio_summary.get("playbook_action", ""),
            "playbook_message": portfolio_summary.get("playbook_message", ""),
            "approval_strip_summary": approval_strip_summary,
            "kill_switch_active": self._safe_bool(safety_state.get("kill_switch_active", False)),
            "close_only_active": self._safe_bool(safety_state.get("close_only_active", False)),
            "config_close_only_active": self._safe_bool(safety_state.get("config_close_only_active", False)),
            "active_locks": list(safety_state.get("active_locks") or []),
            "matching_locks": list(safety_state.get("matching_locks") or []),
            "rollout_policies": list(safety_state.get("rollout_policies") or []),
            "transition_edge_variant": dict(safety_state.get("transition_edge_variant") or {}) or None,
            "session_impulse_retest_universe_policy": dict(safety_state.get("session_impulse_retest_universe_policy") or {}) or None,
            "session_impulse_retest_rollout_readiness": dict(safety_state.get("session_impulse_retest_rollout_readiness") or {}) or None,
            "live_account_protection": dict(safety_state.get("live_account_protection") or {}) or None,
            "recent_intent_count": len(recent_intents),
            "recent_intents": recent_intents,
            "open_order_count": len(open_orders),
            "open_orders": open_orders,
            "open_position_count": len(open_positions),
            "open_positions": open_positions,
            "recent_reconciliation_count": len(reconciliation_events),
            "recent_reconciliation_summary": self._reconciliation_summary(reconciliation_events),
            "recent_reconciliation_events": reconciliation_events,
            "portfolio_summary": portfolio_summary_payload,
            "active_contract": self._active_contract_summary(active_contract_payload),
            "signal_funnel": signal_funnel,
            "alert_summary": self._alert_summary(alert_summary),
            "execution_quality_summary": self._execution_quality_summary(execution_quality_summary),
        }
