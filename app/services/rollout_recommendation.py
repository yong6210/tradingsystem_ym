from __future__ import annotations

from typing import Any

from app.core.enums import ExecutionMode


_MODE_RANK = {
    ExecutionMode.SHADOW.value: 0,
    ExecutionMode.PAPER.value: 1,
    ExecutionMode.MICRO_LIVE.value: 2,
    ExecutionMode.LIVE.value: 3,
}

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_SELECTION_RANK = {"hold": 0, "expand": 1, "research_only": 2, "reduce": 3}


class RolloutRecommendationService:
    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _rows(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
        return [dict(item) for item in list(dict(payload or {}).get(key) or [])]

    @staticmethod
    def _normalize_mode(value: Any) -> str:
        text = str(value or ExecutionMode.SHADOW.value).strip().upper()
        return text if text in _MODE_RANK else ExecutionMode.SHADOW.value

    @staticmethod
    def _default_policy(family: str) -> dict[str, Any]:
        return {
            "strategy_family": str(family or "legacy_zone_plan").lower(),
            "live_enabled": False,
            "max_execution_mode": ExecutionMode.SHADOW.value,
            "max_risk_r": 0.0,
            "allowed_sessions": [],
            "min_quality_score": 0.0,
        }

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
    ) -> str:
        if closed < 4 or execution_confidence == "low" or cls._mode_row_thin(mode_sample_note, execution_confidence):
            return "thin_sample"
        if closed >= 8 and execution_confidence in {"medium", "high"}:
            return "mature"
        return "usable"

    @staticmethod
    def _mode_step(current_mode: str, *, direction: str) -> str:
        rank = _MODE_RANK.get(current_mode, 0)
        target = min(rank + 1, 3) if direction == "up" else max(rank - 1, 0)
        for value, value_rank in _MODE_RANK.items():
            if value_rank == target:
                return value
        return ExecutionMode.SHADOW.value

    @classmethod
    def _suggested_policy_delta(
        cls,
        *,
        recommendation: str,
        current_policy: dict[str, Any],
    ) -> dict[str, Any]:
        current_mode = cls._normalize_mode(current_policy.get("max_execution_mode"))
        current_risk = float(current_policy.get("max_risk_r", 0.0) or 0.0)
        if recommendation == "expand":
            return {
                "action": "expand_consideration",
                "suggested_max_execution_mode": cls._mode_step(current_mode, direction="up"),
                "suggested_max_risk_r": current_risk,
                "change_hint": "incremental_mode_step_only",
            }
        if recommendation == "reduce":
            return {
                "action": "reduce_consideration",
                "suggested_max_execution_mode": cls._mode_step(current_mode, direction="down"),
                "suggested_max_risk_r": round(current_risk * 0.5, 4),
                "change_hint": "reduce_mode_or_risk_after_operator_review",
            }
        if recommendation == "research_only":
            return {
                "action": "keep_research_only",
                "suggested_max_execution_mode": current_mode,
                "suggested_max_risk_r": current_risk,
                "change_hint": "keep_research_bucket_and_collect_evidence",
            }
        return {
            "action": "no_change",
            "suggested_max_execution_mode": current_mode,
            "suggested_max_risk_r": current_risk,
            "change_hint": "keep_current_policy",
        }

    @staticmethod
    def _modifier_row(
        *,
        axis: str,
        outcome_rows: list[dict[str, Any]],
        mode_rows: list[dict[str, Any]],
        positive: bool,
    ) -> dict[str, Any]:
        mode_by_bucket = {str(row.get("bucket") or "unknown"): dict(row) for row in mode_rows}
        for row in outcome_rows:
            item = dict(row)
            closed = int(item.get("closed", 0) or 0)
            rate = float(item.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
            if closed < 4:
                continue
            if positive:
                mode_row = mode_by_bucket.get(str(item.get("key") or "unknown"), {})
                advisory_state = str(mode_row.get("advisory_state") or "keep_current_mode").lower()
                if rate >= 0.5 and advisory_state not in {"watch", "research_only"}:
                    return {
                        "axis": axis,
                        "key": str(item.get("key") or "unknown"),
                        "state": "positive",
                        "closed": closed,
                        "baseline_cost_profitable_rate_from_closed": round(rate, 4),
                    }
            elif rate <= 0.3:
                return {
                    "axis": axis,
                    "key": str(item.get("key") or "unknown"),
                    "state": "negative",
                    "closed": closed,
                    "baseline_cost_profitable_rate_from_closed": round(rate, 4),
                }
        return {}

    @staticmethod
    def _confidence(
        *,
        maturity: str,
        execution_confidence: str,
        mode_sample_note: str,
    ) -> str:
        if maturity == "mature" and execution_confidence == "high" and "thin" not in mode_sample_note.lower():
            return "high"
        if maturity == "usable" or execution_confidence == "medium":
            return "medium"
        return "low"

    @classmethod
    def _reason_codes(
        cls,
        *,
        outcome_state: str,
        execution_state: str,
        mode_state: str,
        maturity: str,
        current_policy: dict[str, Any],
        modifier: dict[str, Any],
        global_execution_status: str,
    ) -> list[str]:
        reason_codes: list[str] = []
        if outcome_state != "unavailable":
            reason_codes.append(f"family_outcome:{outcome_state}")
        if execution_state != "unavailable":
            reason_codes.append(f"family_execution:{execution_state}")
        if mode_state != "unavailable":
            reason_codes.append(f"mode_advisory:{mode_state}")
        reason_codes.append(f"sample:{maturity}")
        current_mode = cls._normalize_mode(current_policy.get("max_execution_mode"))
        reason_codes.append(f"policy:max_mode_{current_mode.lower()}")
        if not bool(current_policy.get("live_enabled", False)):
            reason_codes.append("policy:live_disabled")
        if global_execution_status in {"watch", "manual_review"}:
            reason_codes.append(f"policy:global_execution_{global_execution_status}")
        if modifier:
            reason_codes.append(f"{modifier.get('axis')}_outcome:{modifier.get('state')}")
        deduped: list[str] = []
        for code in reason_codes:
            if code and code not in deduped:
                deduped.append(code)
        return deduped

    @staticmethod
    def _summary(
        *,
        recommendation: str,
        family: str,
        maturity: str,
        outcome_state: str,
        execution_state: str,
        modifier: dict[str, Any],
    ) -> str:
        if recommendation == "expand":
            return (
                f"family={family} has mature positive post-cost evidence and healthy execution; "
                "operator may consider a one-step rollout expansion."
            )
        if recommendation == "reduce":
            return (
                f"family={family} shows execution or post-cost weakness; "
                "review current rollout policy and consider lowering mode or risk."
            )
        if recommendation == "research_only":
            return (
                f"family={family} should remain compare-only research while evidence matures; "
                "keep rollout policy unchanged and collect more outcome data."
            )
        modifier_text = ""
        if modifier:
            modifier_text = (
                f" Top {modifier.get('axis')} modifier is {modifier.get('state')} "
                f"for {modifier.get('key')}."
            )
        return (
            f"family={family} remains in hold; outcome={outcome_state}, execution={execution_state}, "
            f"maturity={maturity} does not justify a rollout change.{modifier_text}"
        )

    def _family_recommendation(
        self,
        *,
        family: str,
        policy: dict[str, Any],
        family_outcome_row: dict[str, Any],
        family_execution_row: dict[str, Any],
        family_mode_row: dict[str, Any],
        regime_negative: dict[str, Any],
        session_negative: dict[str, Any],
        regime_positive: dict[str, Any],
        session_positive: dict[str, Any],
        global_execution_status: str,
    ) -> dict[str, Any]:
        outcome_state, closed, baseline_rate = self._family_outcome_state(family_outcome_row)
        execution_state, execution_confidence = self._family_execution_state(family_execution_row)
        mode_state, _mode_confidence, mode_sample_note = self._family_mode_state(family_mode_row)
        maturity = self._maturity_bucket(
            closed=closed,
            execution_confidence=execution_confidence,
            mode_sample_note=mode_sample_note,
        )

        recommendation = "hold"
        if mode_state == "research_only" or (
            maturity == "thin_sample"
            and (
                execution_state in {"watch", "manual_review"}
                or mode_state == "watch"
                or outcome_state in {"negative", "unavailable"}
            )
        ):
            recommendation = "research_only"
        elif (
            execution_state == "manual_review"
            or (outcome_state == "negative" and execution_state in {"watch", "manual_review"})
            or (execution_state == "watch" and mode_state == "watch")
            or (global_execution_status == "manual_review" and outcome_state in {"mixed", "negative", "unavailable"})
        ):
            recommendation = "hold" if maturity == "thin_sample" else "reduce"
        elif (
            maturity == "mature"
            and outcome_state == "positive"
            and execution_state == "healthy"
            and mode_state in {"keep_current_mode", "promotion_watch", "unavailable"}
            and global_execution_status in {"healthy", "watch"}
        ):
            recommendation = "expand"

        modifier = regime_negative or session_negative or regime_positive or session_positive
        if recommendation == "expand" and modifier and str(modifier.get("state") or "") == "negative":
            recommendation = "hold"

        current_policy = {
            "live_enabled": bool(policy.get("live_enabled", False)),
            "max_execution_mode": self._normalize_mode(policy.get("max_execution_mode")),
            "max_risk_r": float(policy.get("max_risk_r", 0.0) or 0.0),
            "allowed_sessions": list(policy.get("allowed_sessions") or []),
            "min_quality_score": float(policy.get("min_quality_score", 0.0) or 0.0),
        }
        return {
            "available": True,
            "advisory_only": True,
            "family": family,
            "recommendation": recommendation,
            "confidence": self._confidence(
                maturity=maturity,
                execution_confidence=execution_confidence,
                mode_sample_note=mode_sample_note,
            ),
            "maturity": maturity,
            "summary": self._summary(
                recommendation=recommendation,
                family=family,
                maturity=maturity,
                outcome_state=outcome_state,
                execution_state=execution_state,
                modifier=modifier,
            ),
            "reason_codes": self._reason_codes(
                outcome_state=outcome_state,
                execution_state=execution_state,
                mode_state=mode_state,
                maturity=maturity,
                current_policy=current_policy,
                modifier=modifier,
                global_execution_status=global_execution_status,
            ),
            "current_policy": current_policy,
            "suggested_policy_delta": self._suggested_policy_delta(
                recommendation=recommendation,
                current_policy=current_policy,
            ),
            "top_modifier": modifier or None,
            "source_summary": {
                "family_closed": closed,
                "family_baseline_cost_profitable_rate_from_closed": round(baseline_rate, 4),
                "family_execution_status": execution_state,
                "family_mode_advisory_state": mode_state,
                "global_execution_status": global_execution_status,
            },
        }

    def generate(
        self,
        *,
        score_to_outcome_funnel: dict[str, Any] | None,
        execution_degradation_advisory: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        mode_advisory: dict[str, Any] | None,
        rollout_policies: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        funnel_payload = self._dict(score_to_outcome_funnel)
        execution_payload = self._dict(execution_degradation_advisory)
        family_execution_payload = self._dict(family_execution_degradation_advisory)
        mode_payload = self._dict(mode_advisory)
        policies = [dict(item) for item in list(rollout_policies or [])]

        if not any([funnel_payload, execution_payload, family_execution_payload, mode_payload, policies]):
            return {"available": False, "advisory_only": True, "summary": "rollout recommendation unavailable"}

        decomposition = self._dict(funnel_payload.get("decomposition"))
        family_outcome_rows = {
            str(row.get("key") or "unknown"): dict(row) for row in list(decomposition.get("family") or [])
        }
        regime_outcome_rows = self._rows(decomposition, "regime")
        session_outcome_rows = self._rows(decomposition, "session")
        family_execution_rows = {
            str(row.get("family") or "unknown"): dict(row)
            for row in list(family_execution_payload.get("families") or [])
        }
        family_mode_rows = {
            str(row.get("bucket") or "unknown"): dict(row)
            for row in list(mode_payload.get("family") or [])
        }
        regime_mode_rows = self._rows(mode_payload, "regime")
        session_mode_rows = self._rows(mode_payload, "session")
        policy_rows = {
            str(row.get("strategy_family") or "legacy_zone_plan").lower(): dict(row)
            for row in policies
        }
        families = sorted(
            {
                *policy_rows.keys(),
                *family_outcome_rows.keys(),
                *family_execution_rows.keys(),
                *family_mode_rows.keys(),
            }
            - {"", "unknown"}
        )
        if not families:
            return {"available": False, "advisory_only": True, "summary": "rollout recommendation unavailable"}

        regime_negative = self._modifier_row(
            axis="regime",
            outcome_rows=regime_outcome_rows,
            mode_rows=regime_mode_rows,
            positive=False,
        )
        session_negative = self._modifier_row(
            axis="session",
            outcome_rows=session_outcome_rows,
            mode_rows=session_mode_rows,
            positive=False,
        )
        regime_positive = self._modifier_row(
            axis="regime",
            outcome_rows=regime_outcome_rows,
            mode_rows=regime_mode_rows,
            positive=True,
        )
        session_positive = self._modifier_row(
            axis="session",
            outcome_rows=session_outcome_rows,
            mode_rows=session_mode_rows,
            positive=True,
        )
        global_execution_status = str(execution_payload.get("status") or "healthy").lower()
        if global_execution_status not in {"healthy", "watch", "manual_review"}:
            global_execution_status = "healthy"

        candidates: list[dict[str, Any]] = []
        for family in families:
            candidates.append(
                self._family_recommendation(
                    family=family,
                    policy=policy_rows.get(family, self._default_policy(family)),
                    family_outcome_row=family_outcome_rows.get(family, {}),
                    family_execution_row=family_execution_rows.get(family, {}),
                    family_mode_row=family_mode_rows.get(family, {}),
                    regime_negative=regime_negative,
                    session_negative=session_negative,
                    regime_positive=regime_positive,
                    session_positive=session_positive,
                    global_execution_status=global_execution_status,
                )
            )

        candidates.sort(
            key=lambda item: (
                -_SELECTION_RANK.get(str(item.get("recommendation") or "hold"), 0),
                -int(bool(dict(item.get("current_policy") or {}).get("live_enabled", False))),
                -_MODE_RANK.get(
                    str(dict(item.get("current_policy") or {}).get("max_execution_mode") or ExecutionMode.SHADOW.value),
                    0,
                ),
                -_CONFIDENCE_RANK.get(str(item.get("confidence") or "low"), 0),
                -int(dict(item.get("source_summary") or {}).get("family_closed", 0) or 0),
                str(item.get("family") or ""),
            )
        )
        return candidates[0]
