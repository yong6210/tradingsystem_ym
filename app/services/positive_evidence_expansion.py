from __future__ import annotations

from typing import Any


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


class PositiveEvidenceExpansionService:
    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _rows(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
        return [dict(item) for item in list(dict(payload or {}).get(key) or [])]

    @staticmethod
    def _family_outcome_state(row: dict[str, Any]) -> tuple[str, int, float]:
        if not row:
            return "unavailable", 0, 0.0
        closed = int(row.get("closed", 0) or 0)
        rate = float(row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
        if closed < 4:
            return "unavailable", closed, rate
        if rate >= 0.5:
            return "positive", closed, rate
        if rate <= 0.3:
            return "negative", closed, rate
        return "mixed", closed, rate

    @staticmethod
    def _family_execution_state(row: dict[str, Any]) -> tuple[str, str]:
        if not row:
            return "unavailable", "low"
        status = str(row.get("status") or "unavailable").lower()
        confidence = str(row.get("confidence") or "low").lower()
        if status not in {"healthy", "watch", "manual_review"}:
            status = "unavailable"
        if confidence not in _CONFIDENCE_RANK:
            confidence = "low"
        return status, confidence

    @staticmethod
    def _family_mode_state(row: dict[str, Any]) -> tuple[str, str, str]:
        if not row:
            return "unavailable", "low", ""
        advisory_state = str(row.get("advisory_state") or "unavailable").lower()
        confidence = str(row.get("confidence") or "low").lower()
        sample_note = str(row.get("sample_note") or "")
        if advisory_state not in {"research_only", "promotion_watch", "watch", "keep_current_mode"}:
            advisory_state = "unavailable"
        if confidence not in _CONFIDENCE_RANK:
            confidence = "low"
        return advisory_state, confidence, sample_note

    @staticmethod
    def _mode_row_thin(sample_note: str, confidence: str) -> bool:
        return confidence == "low" or "thin" in str(sample_note or "").lower()

    @classmethod
    def _maturity_bucket(
        cls,
        *,
        closed: int,
        execution_confidence: str,
        mode_sample_note: str,
        rollout_maturity: str,
    ) -> str:
        normalized = str(rollout_maturity or "").lower()
        if normalized in {"thin_sample", "usable", "mature"}:
            return normalized
        if closed < 4 or execution_confidence == "low" or cls._mode_row_thin(mode_sample_note, execution_confidence):
            return "thin_sample"
        if closed >= 8 and execution_confidence in {"medium", "high"}:
            return "mature"
        return "usable"

    @staticmethod
    def _modifier_state(rollout_recommendation: dict[str, Any]) -> str:
        state = str(dict(rollout_recommendation.get("top_modifier") or {}).get("state") or "neutral").lower()
        return state if state in {"positive", "negative"} else "neutral"

    @staticmethod
    def _allocator_support_state(capital_allocator: dict[str, Any], family: str) -> str:
        payload = dict(capital_allocator or {})
        if str(payload.get("family_focus") or "").strip().lower() != family:
            return "neutral"
        family_weights = [dict(item) for item in list(payload.get("family_weights") or [])]
        top_row = dict((family_weights[:1] or [{}])[0])
        tier = str(top_row.get("tier") or "neutral").lower()
        return tier if tier in {"boost", "reduce"} else "neutral"

    @classmethod
    def _select_family(
        cls,
        *,
        rollout_recommendation: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        family_outcome_rows: dict[str, dict[str, Any]],
    ) -> str:
        rollout_family = str(rollout_recommendation.get("family") or "").strip().lower()
        if rollout_family and rollout_family != "unknown":
            return rollout_family
        lifecycle_family = str(strategy_lifecycle.get("family") or "").strip().lower()
        if lifecycle_family and lifecycle_family != "unknown":
            return lifecycle_family
        if not family_outcome_rows:
            return ""
        ranked = sorted(
            [dict(row) for row in family_outcome_rows.values()],
            key=lambda row: (
                int(row.get("closed", 0) or 0),
                int(row.get("runtime_candidates", 0) or 0),
                str(row.get("key") or ""),
            ),
            reverse=True,
        )
        return str(dict((ranked[:1] or [{}])[0]).get("key") or "").strip().lower()

    @staticmethod
    def _confidence(
        *,
        state: str,
        maturity: str,
        execution_confidence: str,
        rollout_state: str,
        lifecycle_state: str,
        outcome_state: str,
    ) -> str:
        if (
            state == "expandable"
            and maturity == "mature"
            and execution_confidence == "high"
            and rollout_state == "expand"
            and lifecycle_state == "production"
        ):
            return "high"
        if state == "expandable":
            return "medium"
        if state == "hold" and outcome_state == "positive" and maturity in {"usable", "mature"}:
            return "medium"
        return "low"

    @staticmethod
    def _summary(
        *,
        family: str,
        state: str,
        rollout_state: str,
        modifier_state: str,
        allocator_support_state: str,
        maturity: str,
    ) -> str:
        if state == "expandable":
            summary = (
                f"family={family} has mature positive post-cost evidence and healthy execution; "
                "controlled expansion can be reviewed."
            )
            if rollout_state == "hold":
                summary += " Current rollout policy can remain unchanged until operator review confirms expansion."
            return summary
        if state == "hold":
            summary = (
                f"family={family} shows positive evidence, but guardrails still support a hold posture "
                "before broader expansion."
            )
            if modifier_state == "negative":
                summary += " A negative bucket modifier still argues for caution."
            elif allocator_support_state == "reduce":
                summary += " Current scarce-capital tilt does not support broader expansion."
            elif maturity == "usable":
                summary += " Evidence is usable but not yet mature."
            return summary
        summary = (
            f"family={family} is not ready for positive expansion language because evidence or execution guardrails "
            "remain incomplete."
        )
        if maturity == "thin_sample":
            summary += " The current sample is still too thin."
        return summary

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
        outcome_state: str,
        execution_state: str,
        mode_state: str,
        rollout_state: str,
        lifecycle_state: str,
        allocator_support_state: str,
        modifier_state: str,
        maturity: str,
    ) -> list[str]:
        reasons = [f"positive_expansion:{state}", f"sample:{maturity}"]
        if outcome_state != "unavailable":
            reasons.append(f"family_outcome:{outcome_state}")
        if execution_state != "unavailable":
            reasons.append(f"family_execution:{execution_state}")
        if mode_state != "unavailable":
            reasons.append(f"family_mode:{mode_state}")
        if rollout_state:
            reasons.append(f"rollout_recommendation:{rollout_state}")
        if lifecycle_state:
            reasons.append(f"lifecycle:{lifecycle_state}")
        if allocator_support_state in {"boost", "reduce"}:
            reasons.append(f"allocator:{allocator_support_state}")
        if modifier_state in {"positive", "negative"}:
            reasons.append(f"modifier:{modifier_state}")
        return cls._dedupe(reasons)

    def generate(
        self,
        *,
        score_to_outcome_funnel: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        mode_advisory: dict[str, Any] | None,
        rollout_recommendation: dict[str, Any] | None,
        strategy_lifecycle: dict[str, Any] | None,
        capital_allocator: dict[str, Any] | None,
    ) -> dict[str, Any]:
        funnel_payload = self._dict(score_to_outcome_funnel)
        family_execution_payload = self._dict(family_execution_degradation_advisory)
        mode_payload = self._dict(mode_advisory)
        rollout_payload = self._dict(rollout_recommendation)
        lifecycle_payload = self._dict(strategy_lifecycle)
        allocator_payload = self._dict(capital_allocator)

        if not any(
            [
                funnel_payload,
                family_execution_payload,
                mode_payload,
                rollout_payload,
                lifecycle_payload,
                allocator_payload,
            ]
        ):
            return {"available": False, "advisory_only": True, "summary": "positive evidence expansion unavailable"}

        decomposition = self._dict(funnel_payload.get("decomposition"))
        family_outcome_rows = {
            str(row.get("key") or "unknown"): dict(row) for row in list(decomposition.get("family") or [])
        }
        family_execution_rows = {
            str(row.get("family") or "unknown"): dict(row)
            for row in list(family_execution_payload.get("families") or [])
        }
        family_mode_rows = {
            str(row.get("bucket") or "unknown"): dict(row)
            for row in list(mode_payload.get("family") or [])
        }

        family = self._select_family(
            rollout_recommendation=rollout_payload,
            strategy_lifecycle=lifecycle_payload,
            family_outcome_rows=family_outcome_rows,
        )
        if not family:
            return {"available": False, "advisory_only": True, "summary": "positive evidence expansion unavailable"}

        rollout_state = str(rollout_payload.get("recommendation") or "hold").lower()
        lifecycle_state = str(lifecycle_payload.get("state") or "research").lower()
        modifier_state = self._modifier_state(rollout_payload)
        outcome_state, closed, rate = self._family_outcome_state(family_outcome_rows.get(family, {}))
        execution_state, execution_confidence = self._family_execution_state(family_execution_rows.get(family, {}))
        mode_state, _mode_confidence, mode_sample_note = self._family_mode_state(family_mode_rows.get(family, {}))
        maturity = self._maturity_bucket(
            closed=closed,
            execution_confidence=execution_confidence,
            mode_sample_note=mode_sample_note,
            rollout_maturity=str(rollout_payload.get("maturity") or ""),
        )
        allocator_support_state = self._allocator_support_state(allocator_payload, family)

        state = "hold"
        if (
            maturity == "thin_sample"
            or outcome_state in {"negative", "unavailable"}
            or execution_state in {"watch", "manual_review"}
            or mode_state == "research_only"
            or rollout_state in {"reduce", "research_only"}
            or lifecycle_state in {"research", "degraded", "retired"}
        ):
            state = "not_ready"
        elif (
            maturity == "mature"
            and outcome_state == "positive"
            and execution_state == "healthy"
            and mode_state in {"keep_current_mode", "promotion_watch", "unavailable"}
            and rollout_state in {"expand", "hold"}
            and lifecycle_state in {"production", "probation"}
            and modifier_state != "negative"
        ):
            state = "expandable"

        if state == "expandable" and modifier_state == "negative":
            state = "hold"
        if state == "expandable" and allocator_support_state == "reduce":
            state = "hold"

        expansion_bias = "hold"
        if state == "not_ready":
            expansion_bias = "do_not_expand"
        elif state == "expandable" and rollout_state == "expand" and lifecycle_state in {"production", "probation"}:
            expansion_bias = "consider_expand"

        confidence = self._confidence(
            state=state,
            maturity=maturity,
            execution_confidence=execution_confidence,
            rollout_state=rollout_state,
            lifecycle_state=lifecycle_state,
            outcome_state=outcome_state,
        )

        return {
            "available": True,
            "advisory_only": True,
            "family": family,
            "state": state,
            "expansion_bias": expansion_bias,
            "confidence": confidence,
            "summary": self._summary(
                family=family,
                state=state,
                rollout_state=rollout_state,
                modifier_state=modifier_state,
                allocator_support_state=allocator_support_state,
                maturity=maturity,
            ),
            "reason_codes": self._reason_codes(
                state=state,
                outcome_state=outcome_state,
                execution_state=execution_state,
                mode_state=mode_state,
                rollout_state=rollout_state,
                lifecycle_state=lifecycle_state,
                allocator_support_state=allocator_support_state,
                modifier_state=modifier_state,
                maturity=maturity,
            ),
            "source_summary": {
                "family_closed": closed,
                "family_post_cost_rate": round(rate, 4),
                "family_execution_status": execution_state,
                "family_mode_advisory_state": mode_state,
                "rollout_recommendation": rollout_state or "hold",
                "rollout_maturity": maturity,
                "lifecycle_state": lifecycle_state or "research",
                "allocator_tier": allocator_support_state,
                "modifier_state": modifier_state,
            },
        }
