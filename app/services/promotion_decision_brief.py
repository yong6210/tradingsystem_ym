from __future__ import annotations

from typing import Any


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


class PromotionDecisionBriefService:
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
        promotion_reopen_queue: dict[str, Any],
        promotion_clearance_tracker: dict[str, Any],
        promotion_remediation_queue: dict[str, Any],
        promotion_review_queue: dict[str, Any],
        promotion_governance: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
        capital_allocator: dict[str, Any],
    ) -> str:
        candidates = [
            str(promotion_reopen_queue.get("headline_family") or "").strip().lower(),
            str(promotion_clearance_tracker.get("family") or "").strip().lower(),
            str(promotion_remediation_queue.get("headline_family") or "").strip().lower(),
            str(promotion_review_queue.get("headline_family") or "").strip().lower(),
            str(promotion_governance.get("family") or "").strip().lower(),
            str(strategy_lifecycle.get("family") or "").strip().lower(),
            str(positive_evidence_expansion.get("family") or "").strip().lower(),
            str(capital_allocator.get("family_focus") or "").strip().lower(),
        ]
        for family in candidates:
            if family and family != "unknown":
                return family
        return ""

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

    def _reopen_row(self, *, promotion_reopen_queue: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(promotion_reopen_queue, "reopen_queue")
        }
        return dict(rows.get(family) or {})

    def _allocator_row(self, *, capital_allocator: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(capital_allocator, "family_weights")
        }
        return dict(rows.get(family) or {})

    def _family_execution_status(
        self,
        *,
        family_execution_degradation_advisory: dict[str, Any],
        promotion_governance: dict[str, Any],
        promotion_clearance_tracker: dict[str, Any],
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
        for payload in (promotion_clearance_tracker, promotion_governance):
            if str(payload.get("family") or "").strip().lower() != family:
                continue
            source_summary = dict(payload.get("source_summary") or {})
            status = str(source_summary.get("family_execution_status") or "").lower()
            if status in {"healthy", "watch", "manual_review"}:
                return status
        return "unavailable"

    def generate(
        self,
        *,
        promotion_governance: dict[str, Any] | None,
        promotion_review_queue: dict[str, Any] | None,
        promotion_remediation_queue: dict[str, Any] | None,
        promotion_clearance_tracker: dict[str, Any] | None,
        promotion_reopen_queue: dict[str, Any] | None,
        strategy_lifecycle: dict[str, Any] | None,
        positive_evidence_expansion: dict[str, Any] | None,
        capital_allocator: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
    ) -> dict[str, Any]:
        governance_payload = self._dict(promotion_governance)
        review_payload = self._dict(promotion_review_queue)
        remediation_payload = self._dict(promotion_remediation_queue)
        clearance_payload = self._dict(promotion_clearance_tracker)
        reopen_payload = self._dict(promotion_reopen_queue)
        lifecycle_payload = self._dict(strategy_lifecycle)
        positive_payload = self._dict(positive_evidence_expansion)
        allocator_payload = self._dict(capital_allocator)
        family_execution_payload = self._dict(family_execution_degradation_advisory)

        if not any(
            [
                governance_payload,
                review_payload,
                remediation_payload,
                clearance_payload,
                reopen_payload,
                lifecycle_payload,
                positive_payload,
                allocator_payload,
                family_execution_payload,
            ]
        ):
            return {"available": False, "advisory_only": True, "summary": "promotion decision brief unavailable"}

        family = self._select_family(
            promotion_reopen_queue=reopen_payload,
            promotion_clearance_tracker=clearance_payload,
            promotion_remediation_queue=remediation_payload,
            promotion_review_queue=review_payload,
            promotion_governance=governance_payload,
            strategy_lifecycle=lifecycle_payload,
            positive_evidence_expansion=positive_payload,
            capital_allocator=allocator_payload,
        )
        if not family:
            return {"available": False, "advisory_only": True, "summary": "promotion decision brief unavailable"}

        review_row = self._review_row(promotion_review_queue=review_payload, family=family)
        remediation_row = self._remediation_row(promotion_remediation_queue=remediation_payload, family=family)
        reopen_row = self._reopen_row(promotion_reopen_queue=reopen_payload, family=family)
        governance_state = (
            str(governance_payload.get("state") or "").lower()
            if str(governance_payload.get("family") or "").strip().lower() == family
            else str(review_row.get("promotion_state") or "hold").lower()
        )
        governance_confidence = (
            self._normalize_confidence(governance_payload.get("confidence"))
            if str(governance_payload.get("family") or "").strip().lower() == family
            else self._normalize_confidence(review_row.get("confidence"))
        )
        target_posture = (
            str(governance_payload.get("target_posture") or "keep_current")
            if str(governance_payload.get("family") or "").strip().lower() == family
            else "keep_current"
        )
        clearance_state = (
            str(clearance_payload.get("clearance_state") or "observe_only").lower()
            if str(clearance_payload.get("family") or "").strip().lower() == family
            else str(reopen_row.get("clearance_state") or "observe_only").lower()
        )
        clearance_confidence = (
            self._normalize_confidence(clearance_payload.get("confidence"))
            if str(clearance_payload.get("family") or "").strip().lower() == family
            else self._normalize_confidence(reopen_row.get("confidence"))
        )
        reopen_action = str(reopen_row.get("reopen_action") or reopen_payload.get("top_reopen_action") or "").lower()
        review_action = str(review_row.get("review_action") or review_payload.get("top_review_action") or "").lower()
        remediation_action = str(
            remediation_row.get("remediation_action") or remediation_payload.get("top_remediation_action") or ""
        ).lower()
        lifecycle_state = (
            str(lifecycle_payload.get("state") or "unknown").lower()
            if str(lifecycle_payload.get("family") or "").strip().lower() == family
            else str(dict(governance_payload.get("source_summary") or {}).get("lifecycle_state") or "unknown").lower()
        )
        positive_state = (
            str(positive_payload.get("state") or "").lower()
            if str(positive_payload.get("family") or "").strip().lower() == family
            else ""
        )
        positive_confidence = self._normalize_confidence(
            positive_payload.get("confidence") if str(positive_payload.get("family") or "").strip().lower() == family else None
        )
        allocator_row = self._allocator_row(capital_allocator=allocator_payload, family=family)
        allocator_tier = str(allocator_row.get("tier") or "neutral").lower()
        family_execution_status = self._family_execution_status(
            family_execution_degradation_advisory=family_execution_payload,
            promotion_governance=governance_payload,
            promotion_clearance_tracker=clearance_payload,
            family=family,
        )

        reason_sources: list[str] = []
        if str(governance_payload.get("family") or "").strip().lower() == family:
            reason_sources.extend(list(governance_payload.get("reason_codes") or []))
        if str(clearance_payload.get("family") or "").strip().lower() == family:
            reason_sources.extend(list(clearance_payload.get("reason_codes") or []))
        reason_sources.extend(list(review_row.get("reason_codes") or []))
        reason_sources.extend(list(remediation_row.get("reason_codes") or []))
        reason_sources.extend(list(reopen_row.get("reason_codes") or []))
        reason_sources = self._dedupe(reason_sources)
        thin_sample = "sample:thin_sample" in reason_sources
        active_remediation = remediation_action in {
            "execution_remediation",
            "policy_remediation",
            "condition_remediation",
        }

        if thin_sample or clearance_state == "observe_only" or (lifecycle_state == "research" and not reopen_action):
            brief_state = "observe_case"
        elif (
            reopen_action == "reopen_review"
            and clearance_state == "clearance_ready"
            and family_execution_status != "manual_review"
            and not active_remediation
            and governance_state in {"hold", "promotable"}
        ):
            brief_state = "reopen_candidate"
        else:
            brief_state = "clearance_required"

        if brief_state == "reopen_candidate":
            decision_bias = "consider_reopen_review"
        elif brief_state == "clearance_required":
            decision_bias = "continue_clearance"
        else:
            decision_bias = "observe_only"

        if target_posture not in {"probation", "production", "keep_current"}:
            if brief_state == "reopen_candidate" and lifecycle_state == "probation":
                target_posture = "production"
            elif brief_state == "reopen_candidate" and lifecycle_state == "research":
                target_posture = "probation"
            else:
                target_posture = "keep_current"

        if brief_state == "observe_case":
            confidence = "low"
        elif brief_state == "reopen_candidate":
            confidence = self._normalize_confidence(reopen_row.get("confidence"))
            if confidence == "low":
                confidence = clearance_confidence
            if confidence == "low":
                confidence = governance_confidence
            if confidence == "low" and (positive_state == "expandable" or allocator_tier == "boost"):
                confidence = "medium"
            elif confidence == "medium" and positive_confidence == "high" and allocator_tier == "boost":
                confidence = "high"
        else:
            confidence = clearance_confidence
            if confidence == "low":
                confidence = self._normalize_confidence(remediation_row.get("confidence"))
            if confidence == "low":
                confidence = governance_confidence

        if brief_state == "reopen_candidate":
            summary = f"family={family} can be reviewed as a controlled promotion re-open candidate."
        elif brief_state == "clearance_required":
            summary = f"family={family} still needs guardrail clearing before promotion review should be reopened."
        else:
            summary = f"family={family} remains in observe posture while promotion evidence is still incomplete."

        reason_codes = [
            f"promotion_decision_brief:{brief_state}",
            f"promotion_governance:{governance_state}",
            f"promotion_clearance:{clearance_state}",
        ]
        if review_action:
            reason_codes.append(f"review_queue:{review_action}")
        if remediation_action:
            reason_codes.append(f"remediation_queue:{remediation_action}")
        if reopen_action:
            reason_codes.append(f"promotion_reopen_queue:{reopen_action}")
        if family_execution_status != "unavailable":
            reason_codes.append(f"family_execution:{family_execution_status}")
        if lifecycle_state and lifecycle_state != "unknown":
            reason_codes.append(f"lifecycle:{lifecycle_state}")
        if positive_state:
            reason_codes.append(f"positive_expansion:{positive_state}")
        if allocator_tier in {"boost", "reduce"}:
            reason_codes.append(f"allocator:{allocator_tier}")
        if thin_sample:
            reason_codes.append("sample:thin_sample")

        return {
            "available": True,
            "advisory_only": True,
            "family": family,
            "brief_state": brief_state,
            "decision_bias": decision_bias,
            "target_posture": target_posture,
            "confidence": confidence,
            "summary": summary,
            "reason_codes": self._dedupe(reason_codes),
            "source_summary": {
                "governance_state": governance_state,
                "review_action": review_action,
                "remediation_action": remediation_action,
                "clearance_state": clearance_state,
                "reopen_action": reopen_action,
                "family_execution_status": family_execution_status,
                "lifecycle_state": lifecycle_state,
                "positive_expansion_state": positive_state,
                "allocator_tier": allocator_tier,
            },
        }
