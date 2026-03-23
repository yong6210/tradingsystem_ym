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


class PromotionReviewQueueService:
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

    @classmethod
    def _family_universe(
        cls,
        *,
        promotion_governance: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
        capital_allocator: dict[str, Any],
        score_to_outcome_funnel: dict[str, Any],
    ) -> list[str]:
        families: set[str] = set()
        for payload in (promotion_governance, strategy_lifecycle, positive_evidence_expansion):
            family = str(dict(payload or {}).get("family") or "").strip().lower()
            if family and family != "unknown":
                families.add(family)

        for row in list(dict(capital_allocator or {}).get("family_weights") or []):
            family = str(dict(row).get("family") or "").strip().lower()
            if family and family != "unknown":
                families.add(family)

        decomposition = cls._dict(dict(score_to_outcome_funnel or {}).get("decomposition"))
        for row in cls._rows(decomposition, "family"):
            family = str(dict(row).get("key") or "").strip().lower()
            if family and family != "unknown":
                families.add(family)

        return sorted(families)

    @classmethod
    def _family_outcome_row(cls, *, score_to_outcome_funnel: dict[str, Any], family: str) -> dict[str, Any]:
        decomposition = cls._dict(dict(score_to_outcome_funnel or {}).get("decomposition"))
        rows = {
            str(row.get("key") or "unknown").strip().lower(): dict(row)
            for row in cls._rows(decomposition, "family")
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

    @staticmethod
    def _family_execution_status(row: dict[str, Any]) -> str:
        status = str(dict(row or {}).get("status") or "unavailable").lower()
        return status if status in {"healthy", "watch", "manual_review"} else "unavailable"

    @staticmethod
    def _family_closed_and_rate(row: dict[str, Any]) -> tuple[int, float]:
        normalized = dict(row or {})
        return (
            int(normalized.get("closed", 0) or 0),
            float(normalized.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0),
        )

    @staticmethod
    def _base_priority(review_action: str) -> int:
        if review_action == "promote_review":
            return 10
        if review_action == "defer_review":
            return 20
        return 30

    @staticmethod
    def _review_action_from_state(state: str) -> str:
        if state == "promotable":
            return "promote_review"
        if state == "defer":
            return "defer_review"
        return "hold_monitor"

    @staticmethod
    def _summary(*, family: str, review_action: str) -> str:
        if review_action == "promote_review":
            return f"family={family} should be reviewed first for controlled promotion."
        if review_action == "defer_review":
            return f"family={family} should be reviewed for guardrail causes before any promotion discussion."
        return f"family={family} should remain in the monitor queue while evidence accumulates."

    @staticmethod
    def _queue_state(top_review_action: str, *, has_rows: bool) -> str:
        if not has_rows:
            return "empty_queue"
        if top_review_action == "promote_review":
            return "promotion_ready_queue"
        if top_review_action == "defer_review":
            return "defer_first_queue"
        return "monitor_only_queue"

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    def _primary_row(
        self,
        *,
        family: str,
        promotion_governance: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
        capital_allocator: dict[str, Any],
    ) -> dict[str, Any]:
        promotion_state = str(promotion_governance.get("state") or "hold").lower()
        review_action = self._review_action_from_state(promotion_state)
        lifecycle_state = str(strategy_lifecycle.get("state") or "unknown").lower()
        positive_confidence = self._normalize_confidence(positive_evidence_expansion.get("confidence"))
        confidence = self._normalize_confidence(promotion_governance.get("confidence"))
        allocator_row = self._allocator_row(capital_allocator=capital_allocator, family=family)
        allocator_tier = str(allocator_row.get("tier") or "neutral").lower()
        priority_rank = self._base_priority(review_action)

        if review_action == "promote_review":
            if lifecycle_state == "production":
                priority_rank -= 2
            elif lifecycle_state == "probation":
                priority_rank -= 1
            if positive_confidence == "high":
                priority_rank -= 2
            elif positive_confidence == "medium":
                priority_rank -= 1
            if allocator_tier == "boost":
                priority_rank -= 1
        elif review_action == "defer_review":
            source_summary = dict(promotion_governance.get("source_summary") or {})
            if str(source_summary.get("family_execution_status") or "").lower() == "manual_review":
                priority_rank -= 3
            if lifecycle_state == "retired":
                priority_rank -= 2
            if str(source_summary.get("capital_pressure") or "").lower() == "overallocated_negative":
                priority_rank -= 1
        else:
            if lifecycle_state == "probation":
                priority_rank -= 1
            if str(positive_evidence_expansion.get("state") or "").lower() == "expandable":
                priority_rank -= 1

        return {
            "family": family,
            "review_action": review_action,
            "promotion_state": promotion_state or "hold",
            "target_posture": str(promotion_governance.get("target_posture") or "keep_current"),
            "priority_rank": int(priority_rank),
            "confidence": confidence,
            "summary": self._summary(family=family, review_action=review_action),
            "reason_codes": self._dedupe(list(promotion_governance.get("reason_codes") or [])),
            "_lifecycle_state": lifecycle_state or "unknown",
        }

    def _fallback_row(
        self,
        *,
        family: str,
        score_to_outcome_funnel: dict[str, Any],
        family_execution_degradation_advisory: dict[str, Any],
        capital_allocator: dict[str, Any],
    ) -> dict[str, Any]:
        outcome_row = self._family_outcome_row(score_to_outcome_funnel=score_to_outcome_funnel, family=family)
        execution_row = self._family_execution_row(
            family_execution_degradation_advisory=family_execution_degradation_advisory,
            family=family,
        )
        allocator_row = self._allocator_row(capital_allocator=capital_allocator, family=family)
        closed, rate = self._family_closed_and_rate(outcome_row)
        execution_status = self._family_execution_status(execution_row)
        allocator_tier = str(allocator_row.get("tier") or "neutral").lower()
        capital_pressure = str(allocator_row.get("capital_pressure") or "neutral").lower()

        promotion_state = "hold"
        review_action = "hold_monitor"
        target_posture = "keep_current"
        confidence = "low"
        lifecycle_state = "unknown"

        if execution_status == "manual_review":
            promotion_state = "defer"
            review_action = "defer_review"
            confidence = self._normalize_confidence(execution_row.get("confidence"))
        elif closed < 4:
            promotion_state = "hold"
            review_action = "hold_monitor"
            confidence = "low"
        elif rate >= 0.5 and allocator_tier == "boost":
            confidence = "medium"
        elif rate <= 0.3 or capital_pressure == "overallocated_negative":
            promotion_state = "defer"
            review_action = "defer_review"
            confidence = "medium"

        priority_rank = self._base_priority(review_action)
        if review_action == "defer_review":
            if execution_status == "manual_review":
                priority_rank -= 3
            if capital_pressure == "overallocated_negative":
                priority_rank -= 1

        reason_codes = [
            f"promotion_governance:{promotion_state}",
            f"sample:{'thin_sample' if closed < 4 else 'usable_or_mature'}",
        ]
        if execution_status != "unavailable":
            reason_codes.append(f"family_execution:{execution_status}")
        if allocator_tier in {"boost", "reduce"}:
            reason_codes.append(f"allocator:{allocator_tier}")

        return {
            "family": family,
            "review_action": review_action,
            "promotion_state": promotion_state,
            "target_posture": target_posture,
            "priority_rank": int(priority_rank),
            "confidence": confidence,
            "summary": self._summary(family=family, review_action=review_action),
            "reason_codes": self._dedupe(reason_codes),
            "_lifecycle_state": lifecycle_state,
        }

    def generate(
        self,
        *,
        promotion_governance: dict[str, Any] | None,
        strategy_lifecycle: dict[str, Any] | None,
        positive_evidence_expansion: dict[str, Any] | None,
        capital_allocator: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        score_to_outcome_funnel: dict[str, Any] | None,
    ) -> dict[str, Any]:
        promotion_payload = self._dict(promotion_governance)
        lifecycle_payload = self._dict(strategy_lifecycle)
        positive_payload = self._dict(positive_evidence_expansion)
        allocator_payload = self._dict(capital_allocator)
        family_execution_payload = self._dict(family_execution_degradation_advisory)
        funnel_payload = self._dict(score_to_outcome_funnel)

        if not any(
            [
                promotion_payload,
                lifecycle_payload,
                positive_payload,
                allocator_payload,
                family_execution_payload,
                funnel_payload,
            ]
        ):
            return {"available": False, "advisory_only": True, "summary": "promotion review queue unavailable"}

        families = self._family_universe(
            promotion_governance=promotion_payload,
            strategy_lifecycle=lifecycle_payload,
            positive_evidence_expansion=positive_payload,
            capital_allocator=allocator_payload,
            score_to_outcome_funnel=funnel_payload,
        )
        if not families:
            return {
                "available": True,
                "advisory_only": True,
                "queue_state": "empty_queue",
                "headline_family": "",
                "top_review_action": "",
                "summary": "no family is currently available for promotion review ordering",
                "reason_codes": ["promotion_review_queue:empty_queue"],
                "review_queue": [],
                "source_summary": {
                    "promotion_ready_count": 0,
                    "defer_count": 0,
                    "hold_count": 0,
                    "thin_sample_count": 0,
                    "top_lifecycle_state": "",
                    "top_promotion_state": "",
                    "top_allocator_tier": "",
                },
            }

        primary_family = str(promotion_payload.get("family") or "").strip().lower()
        rows: list[dict[str, Any]] = []
        for family in families:
            if family == primary_family and promotion_payload:
                row = self._primary_row(
                    family=family,
                    promotion_governance=promotion_payload,
                    strategy_lifecycle=lifecycle_payload,
                    positive_evidence_expansion=positive_payload,
                    capital_allocator=allocator_payload,
                )
            else:
                row = self._fallback_row(
                    family=family,
                    score_to_outcome_funnel=funnel_payload,
                    family_execution_degradation_advisory=family_execution_payload,
                    capital_allocator=allocator_payload,
                )
            rows.append(row)

        rows.sort(
            key=lambda row: (
                int(row.get("priority_rank", 999)),
                -int(_CONFIDENCE_RANK.get(str(row.get("confidence") or "low"), 0)),
                int(_LIFECYCLE_SEVERITY_RANK.get(str(row.get("_lifecycle_state") or "unknown"), 5)),
                str(row.get("family") or ""),
            )
        )

        review_queue = [
            {
                "family": str(row.get("family") or ""),
                "review_action": str(row.get("review_action") or "hold_monitor"),
                "promotion_state": str(row.get("promotion_state") or "hold"),
                "target_posture": str(row.get("target_posture") or "keep_current"),
                "priority_rank": int(row.get("priority_rank", 999) or 999),
                "confidence": self._normalize_confidence(row.get("confidence")),
                "summary": str(row.get("summary") or ""),
                "reason_codes": list(row.get("reason_codes") or []),
            }
            for row in rows[:5]
        ]
        top_row = dict((review_queue[:1] or [{}])[0])
        queue_state = self._queue_state(
            str(top_row.get("review_action") or ""),
            has_rows=bool(review_queue),
        )
        thin_sample_count = 0
        decomposition = self._dict(funnel_payload.get("decomposition"))
        family_rows = {
            str(row.get("key") or "unknown").strip().lower(): dict(row)
            for row in self._rows(decomposition, "family")
        }
        for family in families:
            closed, _ = self._family_closed_and_rate(family_rows.get(family, {}))
            if closed < 4:
                thin_sample_count += 1

        source_summary = {
            "promotion_ready_count": sum(1 for row in review_queue if row.get("review_action") == "promote_review"),
            "defer_count": sum(1 for row in review_queue if row.get("review_action") == "defer_review"),
            "hold_count": sum(1 for row in review_queue if row.get("review_action") == "hold_monitor"),
            "thin_sample_count": thin_sample_count,
            "top_lifecycle_state": str(rows[0].get("_lifecycle_state") or "") if rows else "",
            "top_promotion_state": str(top_row.get("promotion_state") or ""),
            "top_allocator_tier": str(
                dict(self._allocator_row(capital_allocator=allocator_payload, family=str(top_row.get("family") or ""))).get(
                    "tier"
                )
                or ""
            ),
        }

        headline_family = str(top_row.get("family") or "")
        top_review_action = str(top_row.get("review_action") or "")
        if queue_state == "promotion_ready_queue":
            summary = (
                f"family={headline_family} is first in the controlled promotion review queue; review promotable families "
                "before lower-priority monitor items."
            )
        elif queue_state == "defer_first_queue":
            summary = (
                f"family={headline_family} should be reviewed first for defer causes before broader promotion review resumes."
            )
        elif queue_state == "monitor_only_queue":
            summary = "current family set remains in monitor queue while evidence accumulates."
        else:
            summary = "no family is currently available for promotion review ordering."

        return {
            "available": True,
            "advisory_only": True,
            "queue_state": queue_state,
            "headline_family": headline_family,
            "top_review_action": top_review_action,
            "summary": summary,
            "reason_codes": self._dedupe(
                [
                    f"promotion_review_queue:{queue_state}",
                    f"headline_family:{headline_family}" if headline_family else "",
                    f"top_review_action:{top_review_action}" if top_review_action else "",
                ]
            ),
            "review_queue": review_queue,
            "source_summary": source_summary,
        }
