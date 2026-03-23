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
_ACTIVE_REMEDIATION_ACTIONS = {
    "execution_remediation",
    "policy_remediation",
    "condition_remediation",
}


class PromotionReopenQueueService:
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
    def _family_universe(
        cls,
        *,
        promotion_governance: dict[str, Any],
        promotion_review_queue: dict[str, Any],
        promotion_remediation_queue: dict[str, Any],
        promotion_clearance_tracker: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
        capital_allocator: dict[str, Any],
    ) -> list[str]:
        families: set[str] = set()
        for payload in (
            promotion_governance,
            promotion_clearance_tracker,
            strategy_lifecycle,
            positive_evidence_expansion,
        ):
            family = str(dict(payload or {}).get("family") or "").strip().lower()
            if family and family != "unknown":
                families.add(family)
        for row in cls._rows(promotion_review_queue, "review_queue"):
            family = str(dict(row).get("family") or "").strip().lower()
            if family and family != "unknown":
                families.add(family)
        for row in cls._rows(promotion_remediation_queue, "remediation_queue"):
            family = str(dict(row).get("family") or "").strip().lower()
            if family and family != "unknown":
                families.add(family)
        for row in cls._rows(capital_allocator, "family_weights"):
            family = str(dict(row).get("family") or "").strip().lower()
            if family and family != "unknown":
                families.add(family)
        return sorted(families)

    @classmethod
    def _review_row(cls, *, promotion_review_queue: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in cls._rows(promotion_review_queue, "review_queue")
        }
        return dict(rows.get(family) or {})

    @classmethod
    def _remediation_row(cls, *, promotion_remediation_queue: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in cls._rows(promotion_remediation_queue, "remediation_queue")
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
        review_row: dict[str, Any],
    ) -> str:
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            return str(promotion_governance.get("state") or "hold").lower()
        return str(review_row.get("promotion_state") or "hold").lower()

    @classmethod
    def _clearance_state(
        cls,
        *,
        family: str,
        promotion_clearance_tracker: dict[str, Any],
    ) -> tuple[str, str]:
        if str(promotion_clearance_tracker.get("family") or "").strip().lower() != family:
            return "observe_only", "low"
        return (
            str(promotion_clearance_tracker.get("clearance_state") or "observe_only").lower(),
            cls._normalize_confidence(promotion_clearance_tracker.get("confidence")),
        )

    @classmethod
    def _family_execution_status(
        cls,
        *,
        family: str,
        family_execution_degradation_advisory: dict[str, Any],
        promotion_governance: dict[str, Any],
        promotion_clearance_tracker: dict[str, Any],
    ) -> str:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in cls._rows(family_execution_degradation_advisory, "families")
        }
        row = dict(rows.get(family) or {})
        status = str(row.get("status") or "").lower()
        if status in {"healthy", "watch", "manual_review"}:
            return status
        if str(promotion_clearance_tracker.get("family") or "").strip().lower() == family:
            source_summary = dict(promotion_clearance_tracker.get("source_summary") or {})
            status = str(source_summary.get("family_execution_status") or "").lower()
            if status in {"healthy", "watch", "manual_review"}:
                return status
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            source_summary = dict(promotion_governance.get("source_summary") or {})
            status = str(source_summary.get("family_execution_status") or "").lower()
            if status in {"healthy", "watch", "manual_review"}:
                return status
        return "unavailable"

    @classmethod
    def _lifecycle_state(
        cls,
        *,
        family: str,
        strategy_lifecycle: dict[str, Any],
        promotion_governance: dict[str, Any],
    ) -> str:
        if str(strategy_lifecycle.get("family") or "").strip().lower() == family:
            return str(strategy_lifecycle.get("state") or "unknown").lower()
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            source_summary = dict(promotion_governance.get("source_summary") or {})
            return str(source_summary.get("lifecycle_state") or "unknown").lower()
        return "unknown"

    @classmethod
    def _positive_state(
        cls,
        *,
        family: str,
        positive_evidence_expansion: dict[str, Any],
    ) -> tuple[str, str]:
        if str(positive_evidence_expansion.get("family") or "").strip().lower() != family:
            return "", "low"
        return (
            str(positive_evidence_expansion.get("state") or "").lower(),
            cls._normalize_confidence(positive_evidence_expansion.get("confidence")),
        )

    @staticmethod
    def _base_priority(action: str) -> int:
        if action == "reopen_review":
            return 10
        if action == "continue_clearance":
            return 20
        return 30

    @staticmethod
    def _queue_state(top_action: str, *, has_rows: bool) -> str:
        if not has_rows:
            return "empty_queue"
        if top_action == "reopen_review":
            return "reopen_ready_queue"
        if top_action == "continue_clearance":
            return "clearance_first_queue"
        return "observe_only_queue"

    @staticmethod
    def _summary(*, family: str, action: str) -> str:
        if action == "reopen_review":
            return f"family={family} should be reviewed first for controlled promotion re-open."
        if action == "continue_clearance":
            return f"family={family} should continue guardrail clearing before promotion review re-opens."
        return f"family={family} should remain in the observe queue while re-open evidence accumulates."

    def _row(
        self,
        *,
        family: str,
        promotion_governance: dict[str, Any],
        promotion_review_queue: dict[str, Any],
        promotion_remediation_queue: dict[str, Any],
        promotion_clearance_tracker: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
        capital_allocator: dict[str, Any],
        family_execution_degradation_advisory: dict[str, Any],
    ) -> dict[str, Any]:
        review_row = self._review_row(promotion_review_queue=promotion_review_queue, family=family)
        remediation_row = self._remediation_row(
            promotion_remediation_queue=promotion_remediation_queue,
            family=family,
        )
        promotion_state = self._promotion_state(
            family=family,
            promotion_governance=promotion_governance,
            review_row=review_row,
        )
        clearance_state, clearance_confidence = self._clearance_state(
            family=family,
            promotion_clearance_tracker=promotion_clearance_tracker,
        )
        review_action = str(review_row.get("review_action") or "hold_monitor").lower()
        remediation_action = str(remediation_row.get("remediation_action") or "").lower()
        family_execution_status = self._family_execution_status(
            family=family,
            family_execution_degradation_advisory=family_execution_degradation_advisory,
            promotion_governance=promotion_governance,
            promotion_clearance_tracker=promotion_clearance_tracker,
        )
        lifecycle_state = self._lifecycle_state(
            family=family,
            strategy_lifecycle=strategy_lifecycle,
            promotion_governance=promotion_governance,
        )
        positive_state, positive_confidence = self._positive_state(
            family=family,
            positive_evidence_expansion=positive_evidence_expansion,
        )
        allocator_row = self._allocator_row(capital_allocator=capital_allocator, family=family)
        allocator_tier = str(allocator_row.get("tier") or "neutral").lower()
        capital_pressure = str(allocator_row.get("capital_pressure") or "neutral").lower()

        reason_sources = []
        if str(promotion_governance.get("family") or "").strip().lower() == family:
            reason_sources.extend(list(promotion_governance.get("reason_codes") or []))
        if str(promotion_clearance_tracker.get("family") or "").strip().lower() == family:
            reason_sources.extend(list(promotion_clearance_tracker.get("reason_codes") or []))
        reason_sources.extend(list(review_row.get("reason_codes") or []))
        reason_sources.extend(list(remediation_row.get("reason_codes") or []))
        reason_sources = self._dedupe(reason_sources)
        thin_sample = "sample:thin_sample" in reason_sources
        active_remediation = remediation_action in _ACTIVE_REMEDIATION_ACTIONS

        if thin_sample or clearance_state == "observe_only":
            reopen_action = "observe_reopen"
        elif (
            clearance_state == "clearance_ready"
            and family_execution_status != "manual_review"
            and not active_remediation
            and promotion_state in {"hold", "promotable"}
            and review_action != "defer_review"
        ):
            reopen_action = "reopen_review"
        else:
            reopen_action = "continue_clearance"

        priority_rank = self._base_priority(reopen_action)
        if reopen_action == "reopen_review":
            priority_rank -= 3
            if review_action == "promote_review":
                priority_rank -= 1
            if positive_state == "expandable":
                priority_rank -= 2
            if positive_confidence == "high":
                priority_rank -= 1
            if allocator_tier == "boost" or capital_pressure == "underallocated_positive":
                priority_rank -= 1
        elif reopen_action == "continue_clearance":
            if family_execution_status == "manual_review":
                priority_rank -= 3
            if remediation_action == "execution_remediation":
                priority_rank -= 2
            elif remediation_action in {"policy_remediation", "condition_remediation"}:
                priority_rank -= 1
            if clearance_state == "blocked":
                priority_rank -= 2
            elif clearance_state == "partial_clear":
                priority_rank -= 1
            if review_action == "defer_review":
                priority_rank -= 1
        else:
            if review_action == "promote_review":
                priority_rank -= 1

        if reopen_action == "observe_reopen":
            confidence = "low"
        elif reopen_action == "reopen_review":
            confidence = clearance_confidence
            if confidence == "low" and positive_confidence in {"medium", "high"}:
                confidence = positive_confidence
            if confidence == "low" and allocator_tier == "boost":
                confidence = "medium"
        else:
            confidence = clearance_confidence
            if confidence == "low":
                confidence = self._normalize_confidence(review_row.get("confidence"))
            if confidence == "low" and family_execution_status == "manual_review":
                confidence = "medium"

        reason_codes = [
            f"promotion_reopen_queue:{reopen_action}",
            f"promotion_clearance:{clearance_state}",
            f"promotion_governance:{promotion_state}",
        ]
        if review_action:
            reason_codes.append(f"review_queue:{review_action}")
        if remediation_action:
            reason_codes.append(f"remediation_queue:{remediation_action}")
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
            "family": family,
            "reopen_action": reopen_action,
            "clearance_state": clearance_state,
            "promotion_state": promotion_state or "hold",
            "priority_rank": int(priority_rank),
            "confidence": self._normalize_confidence(confidence),
            "summary": self._summary(family=family, action=reopen_action),
            "reason_codes": self._dedupe(reason_codes),
            "_lifecycle_state": lifecycle_state or "unknown",
            "_review_priority_rank": int(review_row.get("priority_rank", 999) or 999),
            "_remediation_action": remediation_action,
        }

    def generate(
        self,
        *,
        promotion_governance: dict[str, Any] | None,
        promotion_review_queue: dict[str, Any] | None,
        promotion_remediation_queue: dict[str, Any] | None,
        promotion_clearance_tracker: dict[str, Any] | None,
        strategy_lifecycle: dict[str, Any] | None,
        positive_evidence_expansion: dict[str, Any] | None,
        capital_allocator: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
    ) -> dict[str, Any]:
        promotion_payload = self._dict(promotion_governance)
        review_queue_payload = self._dict(promotion_review_queue)
        remediation_payload = self._dict(promotion_remediation_queue)
        clearance_payload = self._dict(promotion_clearance_tracker)
        lifecycle_payload = self._dict(strategy_lifecycle)
        positive_payload = self._dict(positive_evidence_expansion)
        allocator_payload = self._dict(capital_allocator)
        family_execution_payload = self._dict(family_execution_degradation_advisory)

        if not any(
            [
                promotion_payload,
                review_queue_payload,
                remediation_payload,
                clearance_payload,
                lifecycle_payload,
                positive_payload,
                allocator_payload,
                family_execution_payload,
            ]
        ):
            return {"available": False, "advisory_only": True, "summary": "promotion reopen queue unavailable"}

        families = self._family_universe(
            promotion_governance=promotion_payload,
            promotion_review_queue=review_queue_payload,
            promotion_remediation_queue=remediation_payload,
            promotion_clearance_tracker=clearance_payload,
            strategy_lifecycle=lifecycle_payload,
            positive_evidence_expansion=positive_payload,
            capital_allocator=allocator_payload,
        )
        if not families:
            return {
                "available": True,
                "advisory_only": True,
                "queue_state": "empty_queue",
                "headline_family": "",
                "top_reopen_action": "",
                "summary": "no family is currently available for promotion review re-open ordering",
                "reason_codes": ["promotion_reopen_queue:empty_queue"],
                "reopen_queue": [],
                "source_summary": {
                    "reopen_ready_count": 0,
                    "continue_clearance_count": 0,
                    "observe_count": 0,
                    "thin_sample_count": 0,
                    "top_clearance_state": "",
                    "top_promotion_state": "",
                    "top_remediation_action": "",
                },
            }

        rows = [
            self._row(
                family=family,
                promotion_governance=promotion_payload,
                promotion_review_queue=review_queue_payload,
                promotion_remediation_queue=remediation_payload,
                promotion_clearance_tracker=clearance_payload,
                strategy_lifecycle=lifecycle_payload,
                positive_evidence_expansion=positive_payload,
                capital_allocator=allocator_payload,
                family_execution_degradation_advisory=family_execution_payload,
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

        reopen_queue = [
            {
                "family": str(row.get("family") or ""),
                "reopen_action": str(row.get("reopen_action") or "observe_reopen"),
                "clearance_state": str(row.get("clearance_state") or "observe_only"),
                "promotion_state": str(row.get("promotion_state") or "hold"),
                "priority_rank": int(row.get("priority_rank", 999) or 999),
                "confidence": self._normalize_confidence(row.get("confidence")),
                "summary": str(row.get("summary") or ""),
                "reason_codes": list(row.get("reason_codes") or []),
            }
            for row in rows[:5]
        ]
        top_row = dict((reopen_queue[:1] or [{}])[0])
        queue_state = self._queue_state(str(top_row.get("reopen_action") or ""), has_rows=bool(reopen_queue))
        source_summary = {
            "reopen_ready_count": sum(1 for row in reopen_queue if row.get("reopen_action") == "reopen_review"),
            "continue_clearance_count": sum(
                1 for row in reopen_queue if row.get("reopen_action") == "continue_clearance"
            ),
            "observe_count": sum(1 for row in reopen_queue if row.get("reopen_action") == "observe_reopen"),
            "thin_sample_count": sum(
                1 for row in reopen_queue if "sample:thin_sample" in list(dict(row).get("reason_codes") or [])
            ),
            "top_clearance_state": str(top_row.get("clearance_state") or ""),
            "top_promotion_state": str(top_row.get("promotion_state") or ""),
            "top_remediation_action": str(rows[0].get("_remediation_action") or "") if rows else "",
        }

        headline_family = str(top_row.get("family") or "")
        top_reopen_action = str(top_row.get("reopen_action") or "")
        if queue_state == "reopen_ready_queue":
            summary = (
                f"family={headline_family} is first in the controlled promotion re-open queue; reopen review before "
                "lower-priority clearance or observe items."
            )
        elif queue_state == "clearance_first_queue":
            summary = (
                f"family={headline_family} should continue guardrail clearing before promotion review re-opens."
            )
        elif queue_state == "observe_only_queue":
            summary = "current family set remains in observe re-open queue while evidence accumulates."
        else:
            summary = "no family is currently available for promotion review re-open ordering."

        return {
            "available": True,
            "advisory_only": True,
            "queue_state": queue_state,
            "headline_family": headline_family,
            "top_reopen_action": top_reopen_action,
            "summary": summary,
            "reason_codes": self._dedupe(
                [
                    f"promotion_reopen_queue:{queue_state}",
                    f"headline_family:{headline_family}" if headline_family else "",
                    f"top_reopen_action:{top_reopen_action}" if top_reopen_action else "",
                ]
            ),
            "reopen_queue": reopen_queue,
            "source_summary": source_summary,
        }
