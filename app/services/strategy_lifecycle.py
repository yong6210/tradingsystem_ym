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
_EXECUTION_RANK = {"unavailable": -1, "healthy": 0, "watch": 1, "manual_review": 2}
_MODE_STATE_RANK = {
    "unavailable": -1,
    "keep_current_mode": 0,
    "research_only": 1,
    "watch": 2,
    "promotion_watch": 3,
}


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(default)


class StrategyLifecycleService:
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

    @classmethod
    def _previous_state(cls, current_policy: dict[str, Any]) -> str:
        mode = cls._normalize_mode(current_policy.get("max_execution_mode"))
        live_enabled = _safe_bool(current_policy.get("live_enabled", False))
        if live_enabled and mode in {ExecutionMode.MICRO_LIVE.value, ExecutionMode.LIVE.value}:
            return "production"
        if mode == ExecutionMode.PAPER.value:
            return "probation"
        return "research"

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
    def _alpha_research_signal(alpha_research_pipeline: dict[str, Any]) -> str:
        watchlist = dict(alpha_research_pipeline.get("promotion_watchlist") or {})
        for row in list(watchlist.get("watch_items") or []):
            not_ready = str(row.get("not_ready_reason") or "").strip().lower()
            confidence = str(row.get("confidence") or "low").lower()
            if not_ready in {"", "none"} and confidence in {"medium", "high"}:
                return "promotion_watch"
        if alpha_research_pipeline.get("recommended_action_summary") or bool(
            dict(alpha_research_pipeline.get("research_focus_alignment") or {}).get("available", False)
        ):
            return "research_active"
        return "unavailable"

    @staticmethod
    def _modifier_state(rollout_recommendation: dict[str, Any]) -> str:
        state = str(dict(rollout_recommendation.get("top_modifier") or {}).get("state") or "neutral").lower()
        return state if state in {"positive", "negative"} else "neutral"

    @classmethod
    def _select_family(
        cls,
        *,
        rollout_recommendation: dict[str, Any],
        family_outcome_rows: dict[str, dict[str, Any]],
        family_execution_rows: dict[str, dict[str, Any]],
        family_mode_rows: dict[str, dict[str, Any]],
    ) -> str:
        rollout_family = str(rollout_recommendation.get("family") or "").strip().lower()
        if rollout_family and rollout_family != "unknown":
            return rollout_family

        families = sorted(
            {
                *family_outcome_rows.keys(),
                *family_execution_rows.keys(),
                *family_mode_rows.keys(),
            }
            - {"", "unknown"}
        )
        if not families:
            return ""

        def _rank(family: str) -> tuple[int, int, int, int, str]:
            outcome_row = dict(family_outcome_rows.get(family) or {})
            execution_row = dict(family_execution_rows.get(family) or {})
            mode_row = dict(family_mode_rows.get(family) or {})
            return (
                int(outcome_row.get("closed", 0) or 0),
                int(outcome_row.get("runtime_candidates", 0) or 0),
                int(_EXECUTION_RANK.get(str(execution_row.get("status") or "unavailable").lower(), -1)),
                int(_MODE_STATE_RANK.get(str(mode_row.get("advisory_state") or "unavailable").lower(), -1)),
                family,
            )

        families.sort(key=_rank, reverse=True)
        return families[0]

    @classmethod
    def _state(
        cls,
        *,
        previous_state: str,
        rollout_recommendation: str,
        maturity: str,
        outcome_state: str,
        execution_state: str,
        mode_state: str,
        modifier_state: str,
        alpha_signal: str,
    ) -> str:
        if (
            previous_state in {"probation", "production"}
            and rollout_recommendation == "research_only"
            and maturity != "thin_sample"
            and (
                execution_state == "manual_review"
                or outcome_state == "negative"
                or mode_state == "research_only"
            )
        ):
            return "retired"

        if previous_state in {"probation", "production"} and (
            rollout_recommendation == "reduce"
            or execution_state == "manual_review"
            or (execution_state == "watch" and outcome_state == "negative")
            or (mode_state == "watch" and outcome_state in {"negative", "mixed"})
        ):
            return "degraded"

        if (
            rollout_recommendation in {"expand", "hold"}
            and maturity == "mature"
            and outcome_state == "positive"
            and execution_state == "healthy"
            and mode_state in {"keep_current_mode", "promotion_watch", "unavailable"}
            and modifier_state != "negative"
        ):
            return "production"

        if (
            maturity == "usable"
            and rollout_recommendation in {"hold", "expand"}
            and execution_state in {"healthy", "watch", "unavailable"}
        ):
            return "probation"
        if mode_state == "promotion_watch" and execution_state != "manual_review" and maturity != "thin_sample":
            return "probation"
        if (
            alpha_signal == "promotion_watch"
            and rollout_recommendation in {"hold", "expand"}
            and outcome_state != "negative"
            and maturity != "thin_sample"
        ):
            return "probation"
        if previous_state == "production" and maturity == "usable" and outcome_state in {"mixed", "positive"}:
            return "probation"

        return "research"

    @staticmethod
    def _transition_bias(
        *,
        state: str,
        previous_state: str,
        maturity: str,
    ) -> str:
        if state == "retired":
            return "retire"
        if state == "degraded" or (previous_state == "production" and state == "probation"):
            return "degrade"
        if (previous_state == "research" and state == "probation") or (
            previous_state in {"research", "probation"} and state == "production"
        ):
            return "promote"
        if state == "research" and maturity == "thin_sample":
            return "observe"
        return "hold"

    @staticmethod
    def _confidence(
        *,
        state: str,
        maturity: str,
        execution_confidence: str,
        alpha_signal: str,
    ) -> str:
        if state in {"production", "degraded", "retired"} and maturity == "mature" and execution_confidence in {
            "medium",
            "high",
        }:
            return "high"
        if state == "probation" or maturity == "usable":
            return "medium"
        if alpha_signal == "promotion_watch":
            return "medium"
        return "low"

    @staticmethod
    def _summary(*, family: str, state: str, transition_bias: str) -> str:
        if state == "production":
            return (
                f"family={family} has mature positive post-cost evidence and healthy execution; "
                "keep production governance posture unless rollout or execution evidence weakens."
            )
        if state == "probation":
            return (
                f"family={family} has usable evidence but still sits below stable production posture; "
                "monitor probation before any broader promotion."
            )
        if state == "degraded":
            return (
                f"family={family} has weakened from live-ready posture and should be reviewed in degraded mode "
                "before further rollout."
            )
        if state == "retired":
            return (
                f"family={family} should move out of live rotation and remain as research backlog only "
                "until evidence is rebuilt."
            )
        if transition_bias == "observe":
            return (
                f"family={family} remains research-led and the current window is still too thin to separate "
                "promotion from noise."
            )
        return (
            f"family={family} remains research-led until repeat post-cost evidence and rollout maturity improve."
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
        rollout_recommendation: str,
        outcome_state: str,
        execution_state: str,
        mode_state: str,
        maturity: str,
        alpha_signal: str,
        modifier_state: str,
    ) -> list[str]:
        reasons = [f"lifecycle:{state}"]
        if rollout_recommendation:
            reasons.append(f"rollout_recommendation:{rollout_recommendation}")
        if outcome_state != "unavailable":
            reasons.append(f"family_outcome:{outcome_state}")
        if execution_state != "unavailable":
            reasons.append(f"family_execution:{execution_state}")
        if mode_state != "unavailable":
            reasons.append(f"family_mode:{mode_state}")
        reasons.append(f"sample:{maturity}")
        if alpha_signal == "promotion_watch":
            reasons.append("promotion_watchlist:eligible")
        elif alpha_signal == "research_active":
            reasons.append("alpha_research:research_active")
            reasons.append("promotion_watchlist:inactive")
        else:
            reasons.append("promotion_watchlist:inactive")
        if modifier_state in {"positive", "negative"}:
            reasons.append(f"modifier:{modifier_state}")
        return cls._dedupe(reasons)

    def generate(
        self,
        *,
        alpha_research_pipeline: dict[str, Any] | None,
        score_to_outcome_funnel: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        mode_advisory: dict[str, Any] | None,
        rollout_recommendation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        alpha_payload = self._dict(alpha_research_pipeline)
        funnel_payload = self._dict(score_to_outcome_funnel)
        family_execution_payload = self._dict(family_execution_degradation_advisory)
        mode_payload = self._dict(mode_advisory)
        rollout_payload = self._dict(rollout_recommendation)

        if not any([alpha_payload, funnel_payload, family_execution_payload, mode_payload, rollout_payload]):
            return {"available": False, "advisory_only": True, "summary": "strategy lifecycle unavailable"}

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
            family_outcome_rows=family_outcome_rows,
            family_execution_rows=family_execution_rows,
            family_mode_rows=family_mode_rows,
        )
        if not family:
            return {"available": False, "advisory_only": True, "summary": "strategy lifecycle unavailable"}

        current_policy = dict(rollout_payload.get("current_policy") or {})
        previous_state = self._previous_state(current_policy)
        rollout_state = str(rollout_payload.get("recommendation") or "hold").lower()
        outcome_state, closed, rate = self._family_outcome_state(family_outcome_rows.get(family, {}))
        execution_state, execution_confidence = self._family_execution_state(family_execution_rows.get(family, {}))
        mode_state, _mode_confidence, mode_sample_note = self._family_mode_state(family_mode_rows.get(family, {}))
        maturity = self._maturity_bucket(
            closed=closed,
            execution_confidence=execution_confidence,
            mode_sample_note=mode_sample_note,
            rollout_maturity=str(rollout_payload.get("maturity") or ""),
        )
        alpha_signal = self._alpha_research_signal(alpha_payload)
        modifier_state = self._modifier_state(rollout_payload)

        state = self._state(
            previous_state=previous_state,
            rollout_recommendation=rollout_state,
            maturity=maturity,
            outcome_state=outcome_state,
            execution_state=execution_state,
            mode_state=mode_state,
            modifier_state=modifier_state,
            alpha_signal=alpha_signal,
        )
        transition_bias = self._transition_bias(
            state=state,
            previous_state=previous_state,
            maturity=maturity,
        )
        confidence = self._confidence(
            state=state,
            maturity=maturity,
            execution_confidence=execution_confidence,
            alpha_signal=alpha_signal,
        )

        return {
            "available": True,
            "advisory_only": True,
            "family": family,
            "state": state,
            "previous_state": previous_state,
            "transition_bias": transition_bias,
            "confidence": confidence,
            "summary": self._summary(family=family, state=state, transition_bias=transition_bias),
            "reason_codes": self._reason_codes(
                state=state,
                rollout_recommendation=rollout_state,
                outcome_state=outcome_state,
                execution_state=execution_state,
                mode_state=mode_state,
                maturity=maturity,
                alpha_signal=alpha_signal,
                modifier_state=modifier_state,
            ),
            "source_summary": {
                "family_closed": closed,
                "family_post_cost_rate": round(rate, 4),
                "family_execution_status": execution_state,
                "family_mode_advisory_state": mode_state,
                "rollout_recommendation": rollout_state or "hold",
                "rollout_maturity": maturity,
                "previous_state": previous_state,
                "alpha_research_signal": alpha_signal,
                "modifier_state": modifier_state,
            },
        }
