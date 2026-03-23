from __future__ import annotations

from typing import Any


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_LIFECYCLE_SEVERITY_RANK = {
    "retired": 0,
    "degraded": 1,
    "production": 2,
    "probation": 3,
    "research": 4,
    "unknown": 5,
}
_EXECUTION_GUARDRAILS = {
    "do_not_promote_if_information_failure_persists",
    "do_not_promote_if_forced_exit_remains_elevated",
    "do_not_promote_if_fill_rate_remains_subscale",
}
_CONDITION_GUARDRAILS = {
    "do_not_promote_if_cost_drag_persists",
}
_POLICY_GUARDRAILS = {
    "do_not_expand_rollout_until_ev_is_non_negative",
}


class PromotionRemediationQueueService:
    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _rows(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
        return [dict(item) for item in list(dict(payload or {}).get(key) or [])]

    @staticmethod
    def _normalize_confidence(value: Any) -> str:
        confidence = str(value or "low").lower()
        return confidence if confidence in _CONFIDENCE_RANK else "low"

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    @classmethod
    def _alpha_family_rows(cls, *, alpha_research_pipeline: dict[str, Any], family: str) -> list[dict[str, Any]]:
        rows = []
        for row in list(dict(alpha_research_pipeline or {}).get("recommended_actions") or []):
            normalized = dict(row)
            if str(normalized.get("recommended_scope") or "").lower() != "family":
                continue
            target_family = str(normalized.get("target_family") or "").strip().lower()
            if target_family and target_family == family:
                rows.append(normalized)
        return rows

    @classmethod
    def _family_universe(
        cls,
        *,
        promotion_governance: dict[str, Any],
        promotion_review_queue: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
        capital_allocator: dict[str, Any],
        alpha_research_pipeline: dict[str, Any],
    ) -> list[str]:
        families: set[str] = set()
        for payload in (promotion_governance, strategy_lifecycle, positive_evidence_expansion):
            family = str(dict(payload or {}).get("family") or "").strip().lower()
            if family and family != "unknown":
                families.add(family)
        for row in cls._rows(promotion_review_queue, "review_queue"):
            family = str(dict(row).get("family") or "").strip().lower()
            if family and family != "unknown":
                families.add(family)
        for row in cls._rows(capital_allocator, "family_weights"):
            family = str(dict(row).get("family") or "").strip().lower()
            if family and family != "unknown":
                families.add(family)
        for row in list(dict(alpha_research_pipeline or {}).get("recommended_actions") or []):
            if str(dict(row).get("recommended_scope") or "").lower() != "family":
                continue
            family = str(dict(row).get("target_family") or "").strip().lower()
            if family and family != "unknown":
                families.add(family)
        return sorted(families)

    @classmethod
    def _review_queue_row(cls, *, promotion_review_queue: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in cls._rows(promotion_review_queue, "review_queue")
        }
        return dict(rows.get(family) or {})

    @classmethod
    def _family_execution_row(
        cls,
        *,
        family_execution_degradation_advisory: dict[str, Any],
        family: str,
    ) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in cls._rows(family_execution_degradation_advisory, "families")
        }
        return dict(rows.get(family) or {})

    @classmethod
    def _allocator_row(cls, *, capital_allocator: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in cls._rows(capital_allocator, "family_weights")
        }
        return dict(rows.get(family) or {})

    @classmethod
    def _promotion_state(
        cls,
        *,
        family: str,
        promotion_governance: dict[str, Any],
        review_queue_row: dict[str, Any],
    ) -> str:
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            return str(promotion_governance.get("state") or "hold").lower()
        return str(review_queue_row.get("promotion_state") or "hold").lower()

    @classmethod
    def _review_anchor(
        cls,
        *,
        family: str,
        promotion_governance: dict[str, Any],
        promotion_review_queue: dict[str, Any],
    ) -> tuple[str, int, str]:
        review_row = cls._review_queue_row(promotion_review_queue=promotion_review_queue, family=family)
        review_action = str(review_row.get("review_action") or "hold_monitor").lower()
        priority_rank = int(review_row.get("priority_rank", 999) or 999)
        confidence = cls._normalize_confidence(review_row.get("confidence"))
        if str(promotion_governance.get("family") or "").strip().lower() == family and not review_row:
            confidence = cls._normalize_confidence(promotion_governance.get("confidence"))
        return review_action, priority_rank, confidence

    @classmethod
    def _family_execution_status(
        cls,
        *,
        family: str,
        promotion_governance: dict[str, Any],
        family_execution_degradation_advisory: dict[str, Any],
    ) -> tuple[str, str]:
        row = cls._family_execution_row(
            family_execution_degradation_advisory=family_execution_degradation_advisory,
            family=family,
        )
        status = str(row.get("status") or "").lower()
        if status in {"healthy", "watch", "manual_review"}:
            return status, cls._normalize_confidence(row.get("confidence"))
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            source_summary = dict(promotion_governance.get("source_summary") or {})
            status = str(source_summary.get("family_execution_status") or "").lower()
            if status in {"healthy", "watch", "manual_review"}:
                return status, cls._normalize_confidence(source_summary.get("family_execution_confidence"))
        return "unavailable", "low"

    @classmethod
    def _rollout_state(
        cls,
        *,
        family: str,
        promotion_governance: dict[str, Any],
        rollout_recommendation: dict[str, Any],
    ) -> str:
        if str(rollout_recommendation.get("family") or "").strip().lower() == family:
            return str(rollout_recommendation.get("recommendation") or "").lower()
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            return str(dict(promotion_governance.get("source_summary") or {}).get("rollout_recommendation") or "").lower()
        return ""

    @classmethod
    def _rollout_maturity(
        cls,
        *,
        family: str,
        promotion_governance: dict[str, Any],
        rollout_recommendation: dict[str, Any],
    ) -> str:
        if str(rollout_recommendation.get("family") or "").strip().lower() == family:
            maturity = str(rollout_recommendation.get("maturity") or "").lower()
            if maturity in {"thin_sample", "usable", "mature"}:
                return maturity
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            maturity = str(dict(promotion_governance.get("source_summary") or {}).get("rollout_maturity") or "").lower()
            if maturity in {"thin_sample", "usable", "mature"}:
                return maturity
        return "thin_sample"

    @classmethod
    def _lifecycle_state(
        cls,
        *,
        family: str,
        promotion_governance: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
    ) -> str:
        if str(strategy_lifecycle.get("family") or "").strip().lower() == family:
            return str(strategy_lifecycle.get("state") or "unknown").lower()
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            return str(dict(promotion_governance.get("source_summary") or {}).get("lifecycle_state") or "unknown").lower()
        return "unknown"

    @classmethod
    def _condition_drag(
        cls,
        *,
        family: str,
        outcome_bucket_granularity: dict[str, Any],
    ) -> tuple[str, str, str]:
        family_focus = dict(outcome_bucket_granularity.get("family_focus") or {})
        if str(family_focus.get("key") or "").strip().lower() != family:
            return "neutral", "", "low"
        axis = str(outcome_bucket_granularity.get("top_condition_axis") or "").strip().lower()
        confidence = cls._normalize_confidence(outcome_bucket_granularity.get("confidence"))
        if axis and confidence in {"medium", "high"}:
            return "active", axis, confidence
        return "neutral", "", confidence

    @classmethod
    def _alpha_guardrail_state(
        cls,
        *,
        alpha_research_pipeline: dict[str, Any],
        family: str,
    ) -> tuple[bool, bool, bool, list[str]]:
        rows = cls._alpha_family_rows(alpha_research_pipeline=alpha_research_pipeline, family=family)
        execution = False
        condition = False
        policy = False
        reasons: list[str] = []
        for row in rows:
            focus = str(row.get("focus") or row.get("recommended_action") or "family_research_guardrail")
            reason = f"alpha_research:{focus}"
            guardrails = {str(item or "") for item in list(row.get("promotion_guardrails") or [])}
            if guardrails & _EXECUTION_GUARDRAILS:
                execution = True
                reasons.append(reason)
            if guardrails & _CONDITION_GUARDRAILS:
                condition = True
                reasons.append(reason)
            if guardrails & _POLICY_GUARDRAILS:
                policy = True
                reasons.append(reason)
        return execution, condition, policy, cls._dedupe(reasons)

    @classmethod
    def _thin_sample(
        cls,
        *,
        family: str,
        promotion_governance: dict[str, Any],
        review_queue_row: dict[str, Any],
        rollout_recommendation: dict[str, Any],
    ) -> bool:
        if str(rollout_recommendation.get("family") or "").strip().lower() == family:
            if str(rollout_recommendation.get("maturity") or "").lower() == "thin_sample":
                return True
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            if "sample:thin_sample" in list(promotion_governance.get("reason_codes") or []):
                return True
            if str(dict(promotion_governance.get("source_summary") or {}).get("rollout_maturity") or "").lower() == "thin_sample":
                return True
        return "sample:thin_sample" in list(review_queue_row.get("reason_codes") or [])

    @staticmethod
    def _base_priority(action: str) -> int:
        if action == "execution_remediation":
            return 10
        if action == "policy_remediation":
            return 20
        if action == "condition_remediation":
            return 30
        return 40

    @staticmethod
    def _summary(*, family: str, action: str) -> str:
        if action == "execution_remediation":
            return f"family={family} should review execution drag and exit or fill guardrails before reopening promotion review."
        if action == "policy_remediation":
            return f"family={family} should review rollout and lifecycle posture before promotion review resumes."
        if action == "condition_remediation":
            return f"family={family} should review condition drag buckets before promotion review resumes."
        return f"family={family} should remain in observe queue while evidence accumulates."

    @staticmethod
    def _queue_state(top_action: str, *, has_rows: bool) -> str:
        if not has_rows:
            return "empty_queue"
        if top_action == "execution_remediation":
            return "execution_first_queue"
        if top_action == "policy_remediation":
            return "policy_first_queue"
        if top_action == "condition_remediation":
            return "condition_first_queue"
        return "observe_only_queue"

    def _row(
        self,
        *,
        family: str,
        promotion_governance: dict[str, Any],
        promotion_review_queue: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
        outcome_bucket_granularity: dict[str, Any],
        family_execution_degradation_advisory: dict[str, Any],
        rollout_recommendation: dict[str, Any],
        capital_allocator: dict[str, Any],
        alpha_research_pipeline: dict[str, Any],
    ) -> dict[str, Any]:
        review_queue_row = self._review_queue_row(promotion_review_queue=promotion_review_queue, family=family)
        promotion_state = self._promotion_state(
            family=family,
            promotion_governance=promotion_governance,
            review_queue_row=review_queue_row,
        )
        review_action, review_priority_rank, review_confidence = self._review_anchor(
            family=family,
            promotion_governance=promotion_governance,
            promotion_review_queue=promotion_review_queue,
        )
        family_execution_status, family_execution_confidence = self._family_execution_status(
            family=family,
            promotion_governance=promotion_governance,
            family_execution_degradation_advisory=family_execution_degradation_advisory,
        )
        rollout_state = self._rollout_state(
            family=family,
            promotion_governance=promotion_governance,
            rollout_recommendation=rollout_recommendation,
        )
        rollout_maturity = self._rollout_maturity(
            family=family,
            promotion_governance=promotion_governance,
            rollout_recommendation=rollout_recommendation,
        )
        lifecycle_state = self._lifecycle_state(
            family=family,
            promotion_governance=promotion_governance,
            strategy_lifecycle=strategy_lifecycle,
        )
        condition_drag_state, condition_axis, condition_confidence = self._condition_drag(
            family=family,
            outcome_bucket_granularity=outcome_bucket_granularity,
        )
        allocator_row = self._allocator_row(capital_allocator=capital_allocator, family=family)
        capital_pressure = str(allocator_row.get("capital_pressure") or "neutral").lower()
        positive_state = (
            str(positive_evidence_expansion.get("state") or "").lower()
            if str(positive_evidence_expansion.get("family") or "").strip().lower() == family
            else ""
        )
        alpha_execution, alpha_condition, alpha_policy, alpha_reason_codes = self._alpha_guardrail_state(
            alpha_research_pipeline=alpha_research_pipeline,
            family=family,
        )
        thin_sample = self._thin_sample(
            family=family,
            promotion_governance=promotion_governance,
            review_queue_row=review_queue_row,
            rollout_recommendation=rollout_recommendation,
        )
        context_reason_codes = list(review_queue_row.get("reason_codes") or [])
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            context_reason_codes.extend(list(promotion_governance.get("reason_codes") or []))
        context_reason_codes = self._dedupe(context_reason_codes)

        if thin_sample:
            action = "observe_guardrail"
        elif family_execution_status == "manual_review" or alpha_execution or (
            promotion_state == "defer" and any(code.startswith("family_execution:") for code in context_reason_codes)
        ):
            action = "execution_remediation"
        elif rollout_state in {"reduce", "research_only"} or lifecycle_state in {"degraded", "retired"} or alpha_policy or (
            promotion_state == "defer"
            and any(
                code.startswith("rollout_recommendation:") or code.startswith("lifecycle:")
                for code in context_reason_codes
            )
        ):
            action = "policy_remediation"
        elif condition_drag_state == "active" and promotion_state in {"defer", "hold"}:
            action = "condition_remediation"
        else:
            action = "observe_guardrail"

        priority_rank = self._base_priority(action)
        if action == "execution_remediation":
            if family_execution_status == "manual_review":
                priority_rank -= 3
            if review_action == "defer_review":
                priority_rank -= 1
            if alpha_execution:
                priority_rank -= 1
        elif action == "policy_remediation":
            if lifecycle_state == "retired":
                priority_rank -= 3
            elif lifecycle_state == "degraded":
                priority_rank -= 2
            if rollout_state == "reduce":
                priority_rank -= 2
            elif rollout_state == "research_only":
                priority_rank -= 1
            if capital_pressure == "overallocated_negative":
                priority_rank -= 1
            if review_action == "defer_review":
                priority_rank -= 1
            if alpha_policy:
                priority_rank -= 1
        elif action == "condition_remediation":
            if condition_axis == "cost_condition":
                priority_rank -= 2
            elif condition_axis == "liquidity_condition":
                priority_rank -= 1
            if condition_confidence == "high":
                priority_rank -= 1
            if alpha_condition:
                priority_rank -= 1
        else:
            if review_action == "promote_review":
                priority_rank -= 2
            if positive_state == "expandable":
                priority_rank -= 1

        confidence = review_confidence
        if not review_queue_row and str(promotion_governance.get("family") or "").strip().lower() == family:
            confidence = self._normalize_confidence(promotion_governance.get("confidence"))
        if thin_sample:
            confidence = "low"
        elif confidence == "low" and (alpha_execution or alpha_condition or alpha_policy):
            confidence = "medium"
        elif confidence == "low" and family_execution_confidence in {"medium", "high"} and action == "execution_remediation":
            confidence = family_execution_confidence

        reason_codes = [f"promotion_governance:{promotion_state}"]
        if review_action:
            reason_codes.append(f"review_queue:{review_action}")
        if thin_sample:
            reason_codes.append("sample:thin_sample")
        if family_execution_status != "unavailable":
            reason_codes.append(f"family_execution:{family_execution_status}")
        if rollout_state:
            reason_codes.append(f"rollout_recommendation:{rollout_state}")
        if lifecycle_state and lifecycle_state != "unknown":
            reason_codes.append(f"lifecycle:{lifecycle_state}")
        if condition_drag_state == "active":
            reason_codes.append(f"condition_drag:{condition_axis or 'condition_drag'}")
        if capital_pressure == "overallocated_negative":
            reason_codes.append("allocator:overallocated_negative")
        reason_codes.extend(alpha_reason_codes)

        return {
            "family": family,
            "remediation_action": action,
            "promotion_state": promotion_state or "hold",
            "remediation_domain": action.replace("_remediation", "") if action != "observe_guardrail" else "observe",
            "priority_rank": int(priority_rank),
            "confidence": self._normalize_confidence(confidence),
            "summary": self._summary(family=family, action=action),
            "reason_codes": self._dedupe(reason_codes),
            "_lifecycle_state": lifecycle_state or "unknown",
            "_review_priority_rank": int(review_priority_rank),
        }

    def generate(
        self,
        *,
        promotion_governance: dict[str, Any] | None,
        promotion_review_queue: dict[str, Any] | None,
        strategy_lifecycle: dict[str, Any] | None,
        positive_evidence_expansion: dict[str, Any] | None,
        outcome_bucket_granularity: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        rollout_recommendation: dict[str, Any] | None,
        capital_allocator: dict[str, Any] | None,
        alpha_research_pipeline: dict[str, Any] | None,
    ) -> dict[str, Any]:
        promotion_payload = self._dict(promotion_governance)
        review_queue_payload = self._dict(promotion_review_queue)
        lifecycle_payload = self._dict(strategy_lifecycle)
        positive_payload = self._dict(positive_evidence_expansion)
        bucket_payload = self._dict(outcome_bucket_granularity)
        family_execution_payload = self._dict(family_execution_degradation_advisory)
        rollout_payload = self._dict(rollout_recommendation)
        allocator_payload = self._dict(capital_allocator)
        alpha_payload = self._dict(alpha_research_pipeline)

        if not any(
            [
                promotion_payload,
                review_queue_payload,
                lifecycle_payload,
                positive_payload,
                bucket_payload,
                family_execution_payload,
                rollout_payload,
                allocator_payload,
                alpha_payload,
            ]
        ):
            return {"available": False, "advisory_only": True, "summary": "promotion remediation queue unavailable"}

        families = self._family_universe(
            promotion_governance=promotion_payload,
            promotion_review_queue=review_queue_payload,
            strategy_lifecycle=lifecycle_payload,
            positive_evidence_expansion=positive_payload,
            capital_allocator=allocator_payload,
            alpha_research_pipeline=alpha_payload,
        )
        if not families:
            return {
                "available": True,
                "advisory_only": True,
                "queue_state": "empty_queue",
                "headline_family": "",
                "top_remediation_action": "",
                "summary": "no family is currently available for promotion remediation ordering",
                "reason_codes": ["promotion_remediation_queue:empty_queue"],
                "remediation_queue": [],
                "source_summary": {
                    "execution_first_count": 0,
                    "policy_first_count": 0,
                    "condition_first_count": 0,
                    "observe_count": 0,
                    "thin_sample_count": 0,
                    "top_promotion_state": "",
                    "top_review_action": "",
                    "top_remediation_domain": "",
                },
            }

        rows = [
            self._row(
                family=family,
                promotion_governance=promotion_payload,
                promotion_review_queue=review_queue_payload,
                strategy_lifecycle=lifecycle_payload,
                positive_evidence_expansion=positive_payload,
                outcome_bucket_granularity=bucket_payload,
                family_execution_degradation_advisory=family_execution_payload,
                rollout_recommendation=rollout_payload,
                capital_allocator=allocator_payload,
                alpha_research_pipeline=alpha_payload,
            )
            for family in families
        ]
        rows.sort(
            key=lambda row: (
                int(row.get("priority_rank", 999)),
                int(row.get("_review_priority_rank", 999)),
                -int(_CONFIDENCE_RANK.get(str(row.get("confidence") or "low"), 0)),
                int(_LIFECYCLE_SEVERITY_RANK.get(str(row.get("_lifecycle_state") or "unknown"), 5)),
                str(row.get("family") or ""),
            )
        )

        remediation_queue = [
            {
                "family": str(row.get("family") or ""),
                "remediation_action": str(row.get("remediation_action") or "observe_guardrail"),
                "promotion_state": str(row.get("promotion_state") or "hold"),
                "remediation_domain": str(row.get("remediation_domain") or "observe"),
                "priority_rank": int(row.get("priority_rank", 999) or 999),
                "confidence": self._normalize_confidence(row.get("confidence")),
                "summary": str(row.get("summary") or ""),
                "reason_codes": list(row.get("reason_codes") or []),
            }
            for row in rows[:5]
        ]
        top_row = dict((remediation_queue[:1] or [{}])[0])
        queue_state = self._queue_state(str(top_row.get("remediation_action") or ""), has_rows=bool(remediation_queue))
        thin_sample_count = sum(
            1
            for row in remediation_queue
            if "sample:thin_sample" in list(dict(row).get("reason_codes") or [])
        )
        source_summary = {
            "execution_first_count": sum(
                1 for row in remediation_queue if row.get("remediation_action") == "execution_remediation"
            ),
            "policy_first_count": sum(
                1 for row in remediation_queue if row.get("remediation_action") == "policy_remediation"
            ),
            "condition_first_count": sum(
                1 for row in remediation_queue if row.get("remediation_action") == "condition_remediation"
            ),
            "observe_count": sum(
                1 for row in remediation_queue if row.get("remediation_action") == "observe_guardrail"
            ),
            "thin_sample_count": thin_sample_count,
            "top_promotion_state": str(top_row.get("promotion_state") or ""),
            "top_review_action": str(
                dict(self._review_queue_row(promotion_review_queue=review_queue_payload, family=str(top_row.get("family") or ""))).get(
                    "review_action"
                )
                or ""
            ),
            "top_remediation_domain": str(top_row.get("remediation_domain") or ""),
        }

        headline_family = str(top_row.get("family") or "")
        top_action = str(top_row.get("remediation_action") or "")
        if queue_state == "execution_first_queue":
            summary = (
                f"family={headline_family} should be reviewed first for execution drag and exit or fill guardrails "
                "before promotion review resumes."
            )
        elif queue_state == "policy_first_queue":
            summary = (
                f"family={headline_family} should be reviewed first for rollout and lifecycle posture before "
                "promotion review resumes."
            )
        elif queue_state == "condition_first_queue":
            summary = (
                f"family={headline_family} should be reviewed first for condition drag buckets before promotion "
                "review resumes."
            )
        elif queue_state == "observe_only_queue":
            summary = "current family set remains in observe queue while evidence accumulates."
        else:
            summary = "no family is currently available for promotion remediation ordering."

        return {
            "available": True,
            "advisory_only": True,
            "queue_state": queue_state,
            "headline_family": headline_family,
            "top_remediation_action": top_action,
            "summary": summary,
            "reason_codes": self._dedupe(
                [
                    f"promotion_remediation_queue:{queue_state}",
                    f"headline_family:{headline_family}" if headline_family else "",
                    f"top_remediation_action:{top_action}" if top_action else "",
                ]
            ),
            "remediation_queue": remediation_queue,
            "source_summary": source_summary,
        }
