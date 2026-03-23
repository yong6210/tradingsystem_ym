from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings, get_settings
from app.db.repositories import (
    BinancePositionRepository,
    ExecutionReconciliationEventRepository,
    OrderIntentRepository,
    OrderSubmissionRepository,
)
from app.services.outcome_control_trace import (
    build_outcome_control_trace,
    runtime_outcome_control_trace,
    summarize_outcome_control_trace,
)


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
    "micro_live_session_not_allowed",
}

_QUALITY_REASONS = {
    "risk_budget_below_min",
    "adjusted_score_non_positive",
    "invalid_candidate",
    "sizing_zero_risk",
}

_HARD_GATE_GROUPS = {"safety", "structural"}
_SOFTENING_GATE_GROUPS = {"quality"}


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
        alpha_rows = [row for row in blocked_rows if bool(row.get("alpha_research_candidate"))]
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
            "available": bool(alignment.get("available", False)),
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
            "available": bool(evidence.get("available", False)),
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
            "available": bool(review.get("available", False)),
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
            "available": bool(watchlist.get("available", False)),
            "watchlist_count": int(watchlist.get("watchlist_count", 0) or 0),
            "top_watch": dict((items[:1] or [{}])[0]),
            "watch_items": items[:3],
        }

    @staticmethod
    def _intent_row(row: Any) -> dict[str, Any]:
        approval_snapshot = dict(row.approval_snapshot or {})
        payload = dict(row.payload or {})
        return {
            "intent_id": row.intent_id,
            "plan_id": row.plan_id,
            "symbol": row.symbol,
            "strategy_family": row.strategy_family,
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
            "requested_live": bool(row.requested_live),
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
            "lock_required": bool(row.lock_required),
            "lock_applied": bool(row.lock_applied),
            "lock_scope": row.lock_scope,
            "created_at": row.created_at,
        }

    @staticmethod
    def _reconciliation_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
        if not events:
            return {
                "healthy": True,
                "highest_severity": "INFO",
                "degraded": False,
                "critical_count": 0,
                "lock_required_count": 0,
            }
        highest = max(events, key=lambda item: _SEVERITY_ORDER.get(str(item.get("severity") or "INFO"), 0))
        highest_severity = str(highest.get("severity") or "INFO")
        critical_count = sum(1 for item in events if str(item.get("severity") or "") == "CRITICAL")
        lock_required_count = sum(1 for item in events if bool(item.get("lock_required")))
        degraded = _SEVERITY_ORDER.get(highest_severity, 0) >= _SEVERITY_ORDER["WARNING"]
        return {
            "healthy": not degraded,
            "highest_severity": highest_severity,
            "degraded": degraded,
            "critical_count": critical_count,
            "lock_required_count": lock_required_count,
        }

    @staticmethod
    def _portfolio_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row or {})
        strategy_sizing = dict(item.get("strategy_sizing") or {})
        return {
            "symbol": item.get("symbol", ""),
            "plan_id": item.get("plan_id", ""),
            "strategy_family": item.get("strategy_family", ""),
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
            "capital_allocator": dict(item.get("capital_allocator") or {}),
            "capital_pressure": str(item.get("capital_pressure", "neutral") or "neutral"),
            "strategy_sizing": {
                "outcome_risk_adjustment": dict(strategy_sizing.get("outcome_risk_adjustment") or {}),
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
        return {
            "symbol": payload.get("symbol", ""),
            "fill_rate": payload.get("fill_rate", 0.0),
            "fill_events_total": payload.get("fill_events_total", 0),
            "slippage_bps": dict(payload.get("slippage_bps") or {}),
            "fees": dict(payload.get("fees") or {}),
            "target_exit_ratio": payload.get("target_exit_ratio", 0.0),
            "forced_exit_ratio": payload.get("forced_exit_ratio", 0.0),
            "information_failure_ratio": payload.get("information_failure_ratio", 0.0),
            "time_failure_ratio": payload.get("time_failure_ratio", 0.0),
            "report_path": payload.get("report_path"),
        }

    @staticmethod
    def _score_to_outcome_funnel_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        snapshot = dict(payload.get("snapshot_selection") or {})
        history = dict(payload.get("historical_execution_outcomes") or {})
        decomposition = dict(payload.get("decomposition") or {})
        return {
            "available": bool(payload.get("available", False)),
            "reason": payload.get("reason", "not_available"),
            "report_window_days": int(payload.get("report_window_days", 0) or 0),
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
            "close_rate_from_filled": float(history.get("close_rate_from_filled", 0.0) or 0.0),
            "profitable_rate_from_closed": float(history.get("profitable_rate_from_closed", 0.0) or 0.0),
            "baseline_cost_profitable_rate_from_closed": float(
                history.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0
            ),
            "top_family_bucket": dict((list(decomposition.get("family") or [])[:1] or [{}])[0]),
            "top_regime_bucket": dict((list(decomposition.get("regime") or [])[:1] or [{}])[0]),
            "top_session_bucket": dict((list(decomposition.get("session") or [])[:1] or [{}])[0]),
        }

    @staticmethod
    def _execution_degradation_advisory_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        reasons = list(payload.get("reasons") or [])
        return {
            "available": bool(payload.get("available", False)),
            "status": payload.get("status", "healthy"),
            "healthy": bool(payload.get("healthy", True)),
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
            "available": bool(payload.get("available", False)),
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
            "available": bool(payload.get("available", False)),
            "coverage_note": payload.get("coverage_note"),
            "family_count": len(families),
            "top_family": dict((families[:1] or [{}])[0]),
            "families": [dict(item) for item in families[:3]],
        }

    @staticmethod
    def _operator_action_priority_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        return {
            "available": bool(payload.get("available", False)),
            "top_action": payload.get("top_action", "continue_runtime_monitoring"),
            "top_reason": payload.get("top_reason", ""),
            "priority_level": payload.get("priority_level", "monitor"),
            "priority_source": payload.get("priority_source", "monitor"),
            "action_family": payload.get("action_family", "monitor"),
            "supporting_signals": list(payload.get("supporting_signals") or []),
            "blocking_signals": list(payload.get("blocking_signals") or []),
            "next_actions": [dict(item) for item in list(payload.get("next_actions") or [])[:3]],
            "capture_context": dict(payload.get("capture_context") or {}),
            "advisory_only": bool(payload.get("advisory_only", True)),
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
        execution_friction_measurement_summary: dict[str, Any] | None = None,
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
            for row in self.reconciliation_repo.list_recent(symbol=symbol, limit=reconcile_limit, days=days)
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
            "operator_action_priority": self._operator_action_priority_summary(operator_action_priority_summary),
            "outcome_control_trace": runtime_outcome_trace_summary,
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
            "capital_allocator": dict(portfolio_summary.get("capital_allocator_summary") or {}) or None,
        }

        return {
            "generated_at": datetime.now(timezone.utc),
            "symbol": symbol.upper() if symbol else None,
            "report_window_days": max(int(days), 1),
            "execution_mode": self._execution_mode_value(),
            "auto_trading_enabled": bool(self.settings.auto_trading_enabled),
            "source_of_truth_hint": "execution_runtime_aggregate",
            "new_entries_allowed": bool(safety_state.get("new_entry_allowed", False)),
            "blocking_reason_code": str(safety_state.get("blocking_reason_code", "")),
            "blocking_reason_message": str(safety_state.get("blocking_reason_message", "")),
            "deployment_go_no_go": portfolio_summary.get("deployment_go_no_go", ""),
            "deployment_code": portfolio_summary.get("deployment_code", ""),
            "deployment_message": portfolio_summary.get("deployment_message", ""),
            "playbook_go_no_go": portfolio_summary.get("playbook_go_no_go", ""),
            "playbook_code": portfolio_summary.get("playbook_code", ""),
            "playbook_action": portfolio_summary.get("playbook_action", ""),
            "playbook_message": portfolio_summary.get("playbook_message", ""),
            "kill_switch_active": bool(safety_state.get("kill_switch_active", False)),
            "close_only_active": bool(safety_state.get("close_only_active", False)),
            "config_close_only_active": bool(safety_state.get("config_close_only_active", False)),
            "active_locks": list(safety_state.get("active_locks") or []),
            "matching_locks": list(safety_state.get("matching_locks") or []),
            "rollout_policies": list(safety_state.get("rollout_policies") or []),
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
            "signal_funnel": signal_funnel,
            "alert_summary": self._alert_summary(alert_summary),
            "execution_quality_summary": self._execution_quality_summary(execution_quality_summary),
        }
