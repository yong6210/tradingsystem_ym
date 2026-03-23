from __future__ import annotations

from typing import Any


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


class PromotionClearanceTrackerService:
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

    def _select_family(
        self,
        *,
        promotion_governance: dict[str, Any],
        promotion_remediation_queue: dict[str, Any],
        promotion_review_queue: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
        capital_allocator: dict[str, Any],
    ) -> tuple[str, int]:
        candidates = [
            str(promotion_governance.get("family") or "").strip().lower(),
            str(promotion_remediation_queue.get("headline_family") or "").strip().lower(),
            str(promotion_review_queue.get("headline_family") or "").strip().lower(),
            str(strategy_lifecycle.get("family") or "").strip().lower(),
            str(positive_evidence_expansion.get("family") or "").strip().lower(),
            str(capital_allocator.get("family_focus") or "").strip().lower(),
        ]
        for index, family in enumerate(candidates, start=1):
            if family and family != "unknown":
                return family, index
        return "", 999

    def _review_row(self, *, promotion_review_queue: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(promotion_review_queue, "review_queue")
        }
        return dict(rows.get(family) or {})

    def _remediation_row(self, *, promotion_remediation_queue: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(promotion_remediation_queue, "remediation_queue")
        }
        return dict(rows.get(family) or {})

    def _family_execution_status(
        self,
        *,
        family_execution_degradation_advisory: dict[str, Any],
        promotion_governance: dict[str, Any],
        family: str,
    ) -> str:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(family_execution_degradation_advisory, "families")
        }
        row = dict(rows.get(family) or {})
        status = str(row.get("status") or "").lower()
        if status in {"healthy", "watch", "manual_review"}:
            return status
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            source_summary = dict(promotion_governance.get("source_summary") or {})
            status = str(source_summary.get("family_execution_status") or "").lower()
            if status in {"healthy", "watch", "manual_review"}:
                return status
        return "unavailable"

    def _rollout_state(
        self,
        *,
        rollout_recommendation: dict[str, Any],
        promotion_governance: dict[str, Any],
        family: str,
    ) -> tuple[str, str]:
        if str(rollout_recommendation.get("family") or "").strip().lower() == family:
            return (
                str(rollout_recommendation.get("recommendation") or "").lower(),
                str(rollout_recommendation.get("maturity") or "").lower(),
            )
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            source_summary = dict(promotion_governance.get("source_summary") or {})
            return (
                str(source_summary.get("rollout_recommendation") or "").lower(),
                str(source_summary.get("rollout_maturity") or "").lower(),
            )
        return "", ""

    def _lifecycle_state(
        self,
        *,
        strategy_lifecycle: dict[str, Any],
        promotion_governance: dict[str, Any],
        family: str,
    ) -> str:
        if str(strategy_lifecycle.get("family") or "").strip().lower() == family:
            return str(strategy_lifecycle.get("state") or "unknown").lower()
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            return str(dict(promotion_governance.get("source_summary") or {}).get("lifecycle_state") or "unknown").lower()
        return "unknown"

    def _condition_state(self, *, outcome_bucket_granularity: dict[str, Any], family: str) -> tuple[str, str]:
        family_focus = dict(outcome_bucket_granularity.get("family_focus") or {})
        if str(family_focus.get("key") or "").strip().lower() != family:
            return "cleared", ""
        axis = str(outcome_bucket_granularity.get("top_condition_axis") or "").strip().lower()
        confidence = self._normalize_confidence(outcome_bucket_granularity.get("confidence"))
        if axis and confidence in {"medium", "high"}:
            return "blocked", axis
        return "partial", axis

    def _allocator_row(self, *, capital_allocator: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(capital_allocator, "family_weights")
        }
        return dict(rows.get(family) or {})

    def generate(
        self,
        *,
        promotion_governance: dict[str, Any] | None,
        promotion_review_queue: dict[str, Any] | None,
        promotion_remediation_queue: dict[str, Any] | None,
        strategy_lifecycle: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        rollout_recommendation: dict[str, Any] | None,
        outcome_bucket_granularity: dict[str, Any] | None,
        positive_evidence_expansion: dict[str, Any] | None,
        capital_allocator: dict[str, Any] | None,
    ) -> dict[str, Any]:
        promotion_payload = self._dict(promotion_governance)
        review_payload = self._dict(promotion_review_queue)
        remediation_payload = self._dict(promotion_remediation_queue)
        lifecycle_payload = self._dict(strategy_lifecycle)
        family_execution_payload = self._dict(family_execution_degradation_advisory)
        rollout_payload = self._dict(rollout_recommendation)
        bucket_payload = self._dict(outcome_bucket_granularity)
        positive_payload = self._dict(positive_evidence_expansion)
        allocator_payload = self._dict(capital_allocator)

        if not any(
            [
                promotion_payload,
                review_payload,
                remediation_payload,
                lifecycle_payload,
                family_execution_payload,
                rollout_payload,
                bucket_payload,
                positive_payload,
                allocator_payload,
            ]
        ):
            return {"available": False, "advisory_only": True, "summary": "promotion clearance tracker unavailable"}

        family, family_rank = self._select_family(
            promotion_governance=promotion_payload,
            promotion_remediation_queue=remediation_payload,
            promotion_review_queue=review_payload,
            strategy_lifecycle=lifecycle_payload,
            positive_evidence_expansion=positive_payload,
            capital_allocator=allocator_payload,
        )
        if not family:
            return {"available": False, "advisory_only": True, "summary": "promotion clearance tracker unavailable"}

        review_row = self._review_row(promotion_review_queue=review_payload, family=family)
        remediation_row = self._remediation_row(promotion_remediation_queue=remediation_payload, family=family)
        promotion_state = (
            str(promotion_payload.get("state") or "").lower()
            if str(promotion_payload.get("family") or "").strip().lower() == family
            else str(review_row.get("promotion_state") or "hold").lower()
        )
        governance_confidence = (
            self._normalize_confidence(promotion_payload.get("confidence"))
            if str(promotion_payload.get("family") or "").strip().lower() == family
            else self._normalize_confidence(review_row.get("confidence"))
        )
        review_action = str(review_row.get("review_action") or "hold_monitor").lower()
        remediation_action = str(remediation_row.get("remediation_action") or "").lower()
        family_execution_status = self._family_execution_status(
            family_execution_degradation_advisory=family_execution_payload,
            promotion_governance=promotion_payload,
            family=family,
        )
        rollout_state, rollout_maturity = self._rollout_state(
            rollout_recommendation=rollout_payload,
            promotion_governance=promotion_payload,
            family=family,
        )
        lifecycle_state = self._lifecycle_state(
            strategy_lifecycle=lifecycle_payload,
            promotion_governance=promotion_payload,
            family=family,
        )
        condition_state, top_condition_axis = self._condition_state(
            outcome_bucket_granularity=bucket_payload,
            family=family,
        )
        positive_state = (
            str(positive_payload.get("state") or "").lower()
            if str(positive_payload.get("family") or "").strip().lower() == family
            else ""
        )
        allocator_row = self._allocator_row(capital_allocator=allocator_payload, family=family)
        allocator_tier = str(allocator_row.get("tier") or "").lower()

        reason_sources = []
        if str(promotion_payload.get("family") or "").strip().lower() == family:
            reason_sources.extend(list(promotion_payload.get("reason_codes") or []))
        reason_sources.extend(list(review_row.get("reason_codes") or []))
        reason_sources.extend(list(remediation_row.get("reason_codes") or []))
        reason_sources = self._dedupe(reason_sources)
        thin_sample = "sample:thin_sample" in reason_sources or rollout_maturity == "thin_sample"

        execution_domain_state = "unknown"
        if family_execution_status == "manual_review":
            execution_domain_state = "blocked"
        elif family_execution_status == "watch":
            execution_domain_state = "partial"
        elif family_execution_status == "healthy":
            execution_domain_state = "cleared"

        policy_domain_state = "partial"
        if rollout_state in {"reduce", "research_only"} or lifecycle_state in {"degraded", "retired"}:
            policy_domain_state = "blocked"
        elif rollout_state == "hold" and lifecycle_state in {"probation", "production"}:
            policy_domain_state = "cleared"

        remaining_guardrail_domains: list[str] = []
        if execution_domain_state == "blocked":
            remaining_guardrail_domains.append("execution")
        if policy_domain_state == "blocked":
            remaining_guardrail_domains.append("policy")
        if condition_state == "blocked":
            remaining_guardrail_domains.append("condition")

        cleared_guardrail_domains: list[str] = []
        if execution_domain_state == "cleared":
            cleared_guardrail_domains.append("execution")
        if policy_domain_state == "cleared":
            cleared_guardrail_domains.append("policy")
        if condition_state == "cleared":
            cleared_guardrail_domains.append("condition")

        positive_support = positive_state in {"hold", "expandable"} or (
            allocator_tier == "boost"
            and str(allocator_row.get("capital_pressure") or "").lower() == "underallocated_positive"
        )

        if thin_sample or (promotion_state == "hold" and not remediation_action and not positive_support):
            clearance_state = "observe_only"
        elif len(remaining_guardrail_domains) >= 2:
            clearance_state = "blocked"
        elif len(remaining_guardrail_domains) == 1 and promotion_state == "defer":
            clearance_state = "blocked"
        elif (
            not remaining_guardrail_domains
            and family_execution_status != "manual_review"
            and not thin_sample
            and promotion_state in {"hold", "promotable"}
            and positive_state in {"", "hold", "expandable"}
        ):
            clearance_state = "clearance_ready"
        else:
            clearance_state = "partial_clear"

        if clearance_state == "blocked":
            clearance_bias = "continue_remediation"
        elif clearance_state == "partial_clear":
            clearance_bias = "continue_remediation"
        elif clearance_state == "clearance_ready":
            clearance_bias = "consider_reopen_review"
        else:
            clearance_bias = "observe"

        if thin_sample or family_rank >= 4:
            confidence = "low"
        elif (
            clearance_state == "clearance_ready"
            and governance_confidence in {"medium", "high"}
            and family_execution_status == "healthy"
            and condition_state != "blocked"
        ):
            confidence = "high"
        elif clearance_state == "partial_clear" or (
            clearance_state == "blocked" and len(remaining_guardrail_domains) == 1
        ):
            confidence = "medium"
        else:
            confidence = "low"

        if clearance_state == "blocked":
            summary = "clearance remains blocked while active guardrail domains remain unresolved"
        elif clearance_state == "partial_clear":
            summary = "some remediation has cleared but at least one domain still needs review"
        elif clearance_state == "clearance_ready":
            summary = "guardrail domains appear cleared enough to reopen promotion review"
        else:
            summary = "keep this family in observe tracking while evidence accumulates"

        reason_codes = [f"promotion_clearance:{clearance_state}"]
        if promotion_state:
            reason_codes.append(f"promotion_governance:{promotion_state}")
        if review_action:
            reason_codes.append(f"review_queue:{review_action}")
        if remediation_action:
            reason_codes.append(f"remediation_queue:{remediation_action}")
        if family_execution_status != "unavailable":
            reason_codes.append(f"family_execution:{family_execution_status}")
        if rollout_state:
            reason_codes.append(f"rollout_recommendation:{rollout_state}")
        if lifecycle_state and lifecycle_state != "unknown":
            reason_codes.append(f"lifecycle:{lifecycle_state}")
        if condition_state == "blocked" and top_condition_axis:
            reason_codes.append(f"condition_drag:{top_condition_axis}")
        if allocator_tier:
            reason_codes.append(f"allocator:{allocator_tier}")
        if thin_sample:
            reason_codes.append("sample:thin_sample")

        return {
            "available": True,
            "advisory_only": True,
            "family": family,
            "clearance_state": clearance_state,
            "clearance_bias": clearance_bias,
            "confidence": confidence,
            "summary": f"family={family} {summary}.",
            "reason_codes": self._dedupe(reason_codes),
            "remaining_guardrail_domains": remaining_guardrail_domains,
            "cleared_guardrail_domains": cleared_guardrail_domains,
            "source_summary": {
                "promotion_state": promotion_state,
                "review_action": review_action,
                "remediation_action": remediation_action,
                "family_execution_status": family_execution_status,
                "rollout_recommendation": rollout_state,
                "lifecycle_state": lifecycle_state,
                "top_condition_axis": top_condition_axis,
                "allocator_tier": allocator_tier,
            },
        }
