from __future__ import annotations

from typing import Any


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


class PromotionGovernanceService:
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
    def _select_family(
        cls,
        *,
        strategy_lifecycle: dict[str, Any],
        rollout_recommendation: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
        score_to_outcome_funnel: dict[str, Any],
    ) -> str:
        for payload in (strategy_lifecycle, rollout_recommendation, positive_evidence_expansion):
            family = str(dict(payload or {}).get("family") or "").strip().lower()
            if family and family != "unknown":
                return family

        decomposition = cls._dict(dict(score_to_outcome_funnel or {}).get("decomposition"))
        family_rows = cls._rows(decomposition, "family")
        if not family_rows:
            return ""
        selected = max(
            family_rows,
            key=lambda row: (
                int(row.get("closed", 0) or 0),
                int(row.get("runtime_candidates", 0) or 0),
                str(row.get("key") or ""),
            ),
        )
        return str(dict(selected).get("key") or "").strip().lower()

    @classmethod
    def _family_execution_state(
        cls,
        *,
        family_execution_degradation_advisory: dict[str, Any],
        family: str,
        strategy_lifecycle: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
        rollout_recommendation: dict[str, Any],
    ) -> tuple[str, str]:
        families = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in list(dict(family_execution_degradation_advisory or {}).get("families") or [])
        }
        row = dict(families.get(family) or {})
        if row:
            status = str(row.get("status") or "unavailable").lower()
            confidence = cls._normalize_confidence(row.get("confidence"))
            if status not in {"healthy", "watch", "manual_review"}:
                status = "unavailable"
            return status, confidence

        for payload in (strategy_lifecycle, positive_evidence_expansion, rollout_recommendation):
            source_summary = dict(dict(payload or {}).get("source_summary") or {})
            status = str(source_summary.get("family_execution_status") or "").lower()
            if status in {"healthy", "watch", "manual_review"}:
                confidence = cls._normalize_confidence(source_summary.get("family_execution_confidence"))
                return status, confidence

        return "unavailable", "low"

    @classmethod
    def _family_mode_state(
        cls,
        *,
        mode_advisory: dict[str, Any],
        family: str,
        strategy_lifecycle: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
    ) -> str:
        rows = {
            str(row.get("bucket") or "unknown").strip().lower(): dict(row)
            for row in list(dict(mode_advisory or {}).get("family") or [])
        }
        row = dict(rows.get(family) or {})
        if row:
            advisory_state = str(row.get("advisory_state") or "unavailable").lower()
            if advisory_state in {"research_only", "promotion_watch", "watch", "keep_current_mode"}:
                return advisory_state

        for payload in (strategy_lifecycle, positive_evidence_expansion):
            source_summary = dict(dict(payload or {}).get("source_summary") or {})
            advisory_state = str(source_summary.get("family_mode_advisory_state") or "").lower()
            if advisory_state in {"research_only", "promotion_watch", "watch", "keep_current_mode"}:
                return advisory_state

        return "unavailable"

    @staticmethod
    def _maturity_bucket(
        *,
        rollout_recommendation: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        positive_evidence_expansion: dict[str, Any],
    ) -> str:
        candidates = [
            str(dict(rollout_recommendation or {}).get("maturity") or "").lower(),
            str(dict(dict(strategy_lifecycle or {}).get("source_summary") or {}).get("rollout_maturity") or "").lower(),
            str(
                dict(dict(positive_evidence_expansion or {}).get("source_summary") or {}).get("rollout_maturity") or ""
            ).lower(),
        ]
        for candidate in candidates:
            if candidate in {"thin_sample", "usable", "mature"}:
                return candidate
        return "thin_sample"

    @staticmethod
    def _condition_modifier(outcome_bucket_granularity: dict[str, Any]) -> tuple[str, str, str]:
        payload = dict(outcome_bucket_granularity or {})
        axis = str(payload.get("top_condition_axis") or "").strip().lower()
        confidence = str(payload.get("confidence") or "low").lower()
        if axis and confidence in {"medium", "high"}:
            return "negative", axis, confidence
        return "neutral", "", confidence if confidence in {"medium", "high"} else "low"

    @staticmethod
    def _allocator_modifier(capital_allocator: dict[str, Any], family: str) -> tuple[str, str, str]:
        payload = dict(capital_allocator or {})
        family_focus = str(payload.get("family_focus") or "").strip().lower()
        capital_pressure = str(payload.get("capital_pressure") or "neutral").lower()
        family_weights = [dict(item) for item in list(payload.get("family_weights") or [])]
        family_row = next(
            (row for row in family_weights if str(row.get("family") or "").strip().lower() == family),
            {},
        )
        tier = str(family_row.get("tier") or "neutral").lower()
        if family_focus == family and capital_pressure == "overallocated_negative":
            return "defer_support", tier, capital_pressure
        if family_focus == family and tier == "boost":
            return "boost_support", tier, capital_pressure
        return "neutral", tier, capital_pressure

    @staticmethod
    def _target_posture(*, state: str, lifecycle_state: str) -> str:
        if state == "promotable":
            return "production"
        if state == "hold" and lifecycle_state == "research":
            return "probation"
        return "keep_current"

    @staticmethod
    def _confidence(
        *,
        state: str,
        lifecycle_confidence: str,
        positive_confidence: str,
        family_execution_confidence: str,
        condition_modifier_state: str,
        allocator_modifier_state: str,
    ) -> str:
        if (
            state == "promotable"
            and lifecycle_confidence == "high"
            and positive_confidence in {"medium", "high"}
            and family_execution_confidence in {"medium", "high"}
            and condition_modifier_state != "negative"
        ):
            return "high"
        if state == "promotable":
            return "medium"
        if state == "hold" and lifecycle_confidence in {"medium", "high"}:
            return "medium"
        if allocator_modifier_state == "boost_support" and lifecycle_confidence in {"medium", "high"}:
            return "medium"
        return "low"

    @staticmethod
    def _summary(*, family: str, state: str, target_posture: str) -> str:
        if state == "promotable":
            return (
                f"family={family} is a controlled promotion review candidate; operator can consider a move toward "
                f"{target_posture} posture after governance review."
            )
        if state == "hold":
            return (
                f"family={family} should keep current posture and continue evidence accumulation before promotion review."
            )
        return (
            f"family={family} promotion review should be deferred while guardrails remain active."
        )

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    @classmethod
    def _reason_codes(
        cls,
        *,
        state: str,
        lifecycle_state: str,
        rollout_recommendation: str,
        positive_state: str,
        condition_modifier_state: str,
        condition_axis: str,
        allocator_modifier_state: str,
        family_execution_status: str,
        maturity: str,
    ) -> list[str]:
        reasons = [
            f"promotion_governance:{state}",
            f"sample:{maturity}",
        ]
        if lifecycle_state:
            reasons.append(f"lifecycle:{lifecycle_state}")
        if rollout_recommendation:
            reasons.append(f"rollout_recommendation:{rollout_recommendation}")
        if positive_state:
            reasons.append(f"positive_expansion:{positive_state}")
        if family_execution_status and family_execution_status != "unavailable":
            reasons.append(f"family_execution:{family_execution_status}")
        if condition_modifier_state == "negative":
            reasons.append(f"condition_modifier:{condition_axis or 'condition_drag'}")
        if allocator_modifier_state == "defer_support":
            reasons.append("allocator:overallocated_negative")
        elif allocator_modifier_state == "boost_support":
            reasons.append("allocator:boost")
        return cls._dedupe(reasons)

    def generate(
        self,
        *,
        strategy_lifecycle: dict[str, Any] | None,
        rollout_recommendation: dict[str, Any] | None,
        positive_evidence_expansion: dict[str, Any] | None,
        outcome_bucket_granularity: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        mode_advisory: dict[str, Any] | None,
        capital_allocator: dict[str, Any] | None,
        score_to_outcome_funnel: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        lifecycle_payload = self._dict(strategy_lifecycle)
        rollout_payload = self._dict(rollout_recommendation)
        positive_payload = self._dict(positive_evidence_expansion)
        bucket_payload = self._dict(outcome_bucket_granularity)
        family_execution_payload = self._dict(family_execution_degradation_advisory)
        mode_payload = self._dict(mode_advisory)
        allocator_payload = self._dict(capital_allocator)
        funnel_payload = self._dict(score_to_outcome_funnel)

        if not any(
            [
                lifecycle_payload,
                rollout_payload,
                positive_payload,
                bucket_payload,
                family_execution_payload,
                mode_payload,
                allocator_payload,
                funnel_payload,
            ]
        ):
            return {"available": False, "advisory_only": True, "summary": "promotion governance unavailable"}

        family = self._select_family(
            strategy_lifecycle=lifecycle_payload,
            rollout_recommendation=rollout_payload,
            positive_evidence_expansion=positive_payload,
            score_to_outcome_funnel=funnel_payload,
        )
        if not family:
            return {"available": False, "advisory_only": True, "summary": "promotion governance unavailable"}

        lifecycle_state = str(lifecycle_payload.get("state") or "research").lower()
        lifecycle_confidence = self._normalize_confidence(lifecycle_payload.get("confidence"))
        rollout_state = str(rollout_payload.get("recommendation") or "hold").lower()
        positive_state = str(positive_payload.get("state") or "not_ready").lower()
        positive_bias = str(positive_payload.get("expansion_bias") or "hold").lower()
        positive_confidence = self._normalize_confidence(positive_payload.get("confidence"))
        family_execution_status, family_execution_confidence = self._family_execution_state(
            family_execution_degradation_advisory=family_execution_payload,
            family=family,
            strategy_lifecycle=lifecycle_payload,
            positive_evidence_expansion=positive_payload,
            rollout_recommendation=rollout_payload,
        )
        family_mode_state = self._family_mode_state(
            mode_advisory=mode_payload,
            family=family,
            strategy_lifecycle=lifecycle_payload,
            positive_evidence_expansion=positive_payload,
        )
        maturity = self._maturity_bucket(
            rollout_recommendation=rollout_payload,
            strategy_lifecycle=lifecycle_payload,
            positive_evidence_expansion=positive_payload,
        )
        condition_modifier_state, condition_axis, condition_confidence = self._condition_modifier(bucket_payload)
        allocator_modifier_state, allocator_tier, capital_pressure = self._allocator_modifier(allocator_payload, family)

        defer_state = any(
            [
                lifecycle_state in {"research", "degraded", "retired"},
                rollout_state in {"reduce", "research_only"},
                positive_state == "not_ready",
                family_execution_status == "manual_review",
                maturity == "thin_sample",
                condition_modifier_state == "negative",
                allocator_modifier_state == "defer_support",
            ]
        )
        promotable_state = all(
            [
                lifecycle_state in {"probation", "production"},
                positive_state == "expandable",
                positive_bias == "consider_expand",
                rollout_state in {"hold", "expand"},
                family_execution_status == "healthy",
                maturity != "thin_sample",
                condition_modifier_state != "negative",
            ]
        )

        if defer_state:
            state = "defer"
        elif promotable_state:
            state = "promotable"
        else:
            state = "hold"

        promotion_bias = "hold"
        if state == "promotable":
            promotion_bias = "consider_promote"
        elif state == "defer":
            promotion_bias = "defer"

        target_posture = self._target_posture(state=state, lifecycle_state=lifecycle_state)
        confidence = self._confidence(
            state=state,
            lifecycle_confidence=lifecycle_confidence,
            positive_confidence=positive_confidence,
            family_execution_confidence=family_execution_confidence,
            condition_modifier_state=condition_modifier_state,
            allocator_modifier_state=allocator_modifier_state,
        )

        return {
            "available": True,
            "advisory_only": True,
            "family": family,
            "state": state,
            "promotion_bias": promotion_bias,
            "target_posture": target_posture,
            "confidence": confidence,
            "summary": self._summary(family=family, state=state, target_posture=target_posture),
            "reason_codes": self._reason_codes(
                state=state,
                lifecycle_state=lifecycle_state,
                rollout_recommendation=rollout_state,
                positive_state=positive_state,
                condition_modifier_state=condition_modifier_state,
                condition_axis=condition_axis,
                allocator_modifier_state=allocator_modifier_state,
                family_execution_status=family_execution_status,
                maturity=maturity,
            ),
            "source_summary": {
                "lifecycle_state": lifecycle_state or "research",
                "lifecycle_confidence": lifecycle_confidence,
                "rollout_recommendation": rollout_state or "hold",
                "rollout_maturity": maturity,
                "positive_expansion_state": positive_state or "not_ready",
                "positive_expansion_bias": positive_bias or "hold",
                "positive_expansion_confidence": positive_confidence,
                "family_execution_status": family_execution_status,
                "family_execution_confidence": family_execution_confidence,
                "family_mode_advisory_state": family_mode_state,
                "condition_modifier_state": condition_modifier_state,
                "condition_modifier_axis": condition_axis,
                "condition_modifier_confidence": condition_confidence,
                "allocator_tier": allocator_tier,
                "capital_pressure": capital_pressure,
            },
        }
