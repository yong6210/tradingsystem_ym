from __future__ import annotations

from typing import Any


_CONFIDENCE_RANK = {
    "low": 0,
    "medium": 1,
    "high": 2,
}


class ResearchPromotionOperatingLoopService:
    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _rows(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
        return [dict(item) for item in list(dict(payload or {}).get(key) or [])]

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    @classmethod
    def _confidence(cls, *values: str) -> str:
        selected = "low"
        for value in values:
            normalized = str(value or "low").strip().lower()
            if _CONFIDENCE_RANK.get(normalized, 0) > _CONFIDENCE_RANK.get(selected, 0):
                selected = normalized
        return selected

    def _select_family(
        self,
        *,
        alpha_research_pipeline: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        promotion_governance: dict[str, Any],
        promotion_review_queue: dict[str, Any],
        promotion_decision_brief: dict[str, Any],
    ) -> str:
        alpha_summary = dict(alpha_research_pipeline.get("summary") or {})
        recommended_action_summary = dict(alpha_research_pipeline.get("recommended_action_summary") or {})
        candidates = [
            str(promotion_decision_brief.get("family") or "").strip().lower(),
            str(promotion_governance.get("family") or "").strip().lower(),
            str(strategy_lifecycle.get("family") or "").strip().lower(),
            str(alpha_summary.get("top_family") or "").strip().lower(),
            (
                str(recommended_action_summary.get("bucket") or "").strip().lower()
                if str(recommended_action_summary.get("recommended_scope") or "").strip().lower() == "family"
                else ""
            ),
            str(promotion_review_queue.get("headline_family") or "").strip().lower(),
        ]
        for family in candidates:
            if family and family != "unknown":
                return family
        return ""

    def _top_watch(self, *, alpha_research_pipeline: dict[str, Any]) -> dict[str, Any]:
        watchlist = dict(alpha_research_pipeline.get("promotion_watchlist") or {})
        return dict((list(watchlist.get("watch_items") or [])[:1] or [{}])[0])

    def _family_execution_status(
        self,
        *,
        family_execution_degradation_advisory: dict[str, Any],
        family: str,
    ) -> str:
        normalized_family = str(family or "").strip().lower()
        for row in self._rows(family_execution_degradation_advisory, "families"):
            if str(row.get("family") or "").strip().lower() == normalized_family:
                return str(row.get("status") or "unknown").strip().lower()
        return "unknown"

    @staticmethod
    def _cluster_status(*, multi_strategy_ab: dict[str, Any], family: str) -> str:
        normalized_family = str(family or "").strip().lower()
        raw_anchor = str(multi_strategy_ab.get("raw_family_anchor") or "").strip().lower()
        if normalized_family and normalized_family == raw_anchor:
            return str((dict(multi_strategy_ab.get("a_cluster") or {})).get("strategy_cluster_status") or "")
        if normalized_family and raw_anchor and normalized_family != raw_anchor:
            return str((dict(multi_strategy_ab.get("b_cluster") or {})).get("strategy_cluster_status") or "")
        return ""

    @staticmethod
    def _summary(*, family: str, loop_state: str) -> str:
        if loop_state == "promotion_followthrough":
            return (
                f"family={family} has moved beyond research into promotion followthrough; keep governance and proposal execution aligned."
            )
        if loop_state == "probation_candidate":
            return (
                f"family={family} has enough research/watch evidence to prepare a probation review, but it remains compare-only."
            )
        if loop_state == "shadow_test_ready":
            return (
                f"family={family} has a concrete shadow-test path; queue the research test before any probation or promotion move."
            )
        return f"family={family} remains in research backlog; keep gathering shadow evidence before promotion review."

    def generate(
        self,
        *,
        alpha_research_pipeline: dict[str, Any] | None,
        strategy_lifecycle: dict[str, Any] | None,
        promotion_governance: dict[str, Any] | None,
        promotion_review_queue: dict[str, Any] | None,
        promotion_decision_brief: dict[str, Any] | None,
        auto_promotion_rollout_execution: dict[str, Any] | None,
        promotion_lifecycle_history: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        multi_strategy_ab: dict[str, Any] | None,
    ) -> dict[str, Any]:
        alpha_payload = self._dict(alpha_research_pipeline)
        lifecycle_payload = self._dict(strategy_lifecycle)
        governance_payload = self._dict(promotion_governance)
        review_payload = self._dict(promotion_review_queue)
        brief_payload = self._dict(promotion_decision_brief)
        auto_execution_payload = self._dict(auto_promotion_rollout_execution)
        history_payload = self._dict(promotion_lifecycle_history)
        family_execution_payload = self._dict(family_execution_degradation_advisory)
        multi_strategy_payload = self._dict(multi_strategy_ab)

        if not any(
            [
                alpha_payload,
                lifecycle_payload,
                governance_payload,
                review_payload,
                brief_payload,
                auto_execution_payload,
                history_payload,
            ]
        ):
            return {
                "available": False,
                "advisory_only": True,
                "summary": "research promotion operating loop unavailable",
            }

        family = self._select_family(
            alpha_research_pipeline=alpha_payload,
            strategy_lifecycle=lifecycle_payload,
            promotion_governance=governance_payload,
            promotion_review_queue=review_payload,
            promotion_decision_brief=brief_payload,
        )
        alpha_summary = dict(alpha_payload.get("summary") or {})
        recommended_action_summary = dict(alpha_payload.get("recommended_action_summary") or {})
        top_shadow_experiment = dict(alpha_payload.get("top_shadow_experiment") or {})
        top_watch = self._top_watch(alpha_research_pipeline=alpha_payload)

        if not family:
            family = str(alpha_summary.get("top_family") or "").strip().lower()
        if not family and str(recommended_action_summary.get("recommended_scope") or "").strip().lower() == "family":
            family = str(recommended_action_summary.get("bucket") or "").strip().lower()
        if not family:
            return {
                "available": False,
                "advisory_only": True,
                "summary": "research promotion operating loop unavailable",
            }

        governance_state = str(governance_payload.get("state") or "defer").strip().lower()
        governance_target_posture = str(governance_payload.get("target_posture") or "keep_current").strip().lower()
        brief_state = str(brief_payload.get("brief_state") or "observe_case").strip().lower()
        execution_stage = str(auto_execution_payload.get("execution_stage") or "advisory_only").strip().lower()
        history_state = str(history_payload.get("history_state") or "history_unavailable").strip().lower()
        family_execution_status = self._family_execution_status(
            family_execution_degradation_advisory=family_execution_payload,
            family=family,
        )
        cluster_status = self._cluster_status(multi_strategy_ab=multi_strategy_payload, family=family)

        recommended_action = str(
            recommended_action_summary.get("recommended_action")
            or top_shadow_experiment.get("recommended_action")
            or ""
        ).strip()
        shadow_experiment_id = str(
            top_shadow_experiment.get("experiment_id") or top_watch.get("recent_shadow_template") or ""
        ).strip()
        watchlist_ready = bool(top_watch) and not str(top_watch.get("not_ready_reason") or "").strip()
        research_candidate_count = int(alpha_summary.get("alpha_research_candidate_count", 0) or 0)
        thin_sample = (
            str(recommended_action_summary.get("confidence") or top_watch.get("confidence") or "low").strip().lower()
            == "low"
        )
        history_attention = history_state == "history_attention_required"
        manual_review = family_execution_status == "manual_review"
        guarded_watch = brief_state == "clearance_required"

        loop_state = "research_backlog"
        loop_bias = "observe_only"
        target_stage = "research"
        if (
            execution_stage in {"dry_run_execution", "semi_auto_candidate"}
            and governance_state == "promotable"
            and not guarded_watch
            and not history_attention
            and not manual_review
            and not thin_sample
        ):
            loop_state = "promotion_followthrough"
            loop_bias = "follow_promotion_path"
            target_stage = "promoted" if governance_target_posture == "production" else "probation"
        elif (
            watchlist_ready
            and governance_state in {"hold", "promotable"}
            and not guarded_watch
            and not history_attention
            and not manual_review
            and not thin_sample
        ):
            loop_state = "probation_candidate"
            loop_bias = "prepare_probation_review"
            target_stage = "probation"
        elif recommended_action or shadow_experiment_id:
            loop_state = "shadow_test_ready"
            loop_bias = "queue_shadow_test"
            target_stage = "tested"
        elif research_candidate_count > 0:
            loop_state = "research_backlog"
            loop_bias = "continue_shadow_test"
            target_stage = "research"

        confidence = self._confidence(
            str(recommended_action_summary.get("confidence") or ""),
            str(top_shadow_experiment.get("confidence") or ""),
            str(top_watch.get("confidence") or ""),
            str(governance_payload.get("confidence") or ""),
            str(brief_payload.get("confidence") or ""),
            str(auto_execution_payload.get("confidence") or ""),
        )
        reason_codes = self._dedupe(
            [
                f"research_loop:{loop_state}",
                f"target_stage:{target_stage}",
                f"governance:{governance_state}",
                f"brief:{brief_state}",
                f"execution_stage:{execution_stage}",
                f"history:{history_state}",
                f"family_execution:{family_execution_status}",
                *list(alpha_payload.get("reason_codes") or []),
                *list(top_watch.get("reason_codes") or []),
                *list(governance_payload.get("reason_codes") or []),
                *list(brief_payload.get("reason_codes") or []),
                *list(auto_execution_payload.get("reason_codes") or []),
                *list(history_payload.get("reason_codes") or []),
            ]
        )

        return {
            "available": True,
            "advisory_only": True,
            "family": family,
            "loop_state": loop_state,
            "loop_bias": loop_bias,
            "target_stage": target_stage,
            "recommended_action": recommended_action or None,
            "shadow_experiment_id": shadow_experiment_id or None,
            "watchlist_ready": watchlist_ready,
            "confidence": confidence,
            "summary": self._summary(family=family, loop_state=loop_state),
            "reason_codes": reason_codes,
            "source_summary": {
                "recommended_scope": str(recommended_action_summary.get("recommended_scope") or ""),
                "recommended_bucket": str(recommended_action_summary.get("bucket") or ""),
                "watchlist_not_ready_reason": str(top_watch.get("not_ready_reason") or ""),
                "governance_state": governance_state,
                "governance_target_posture": governance_target_posture,
                "brief_state": brief_state,
                "execution_stage": execution_stage,
                "history_state": history_state,
                "family_execution_status": family_execution_status,
                "strategy_cluster_status": cluster_status,
            },
        }
