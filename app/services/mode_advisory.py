from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.core.config import Settings, get_settings


class ModeAdvisoryService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @staticmethod
    def _focus_axis(value: str | None) -> str:
        focus = str(value or "")
        if focus.startswith("family_"):
            return "family"
        if focus.startswith("regime_"):
            return "regime"
        if focus.startswith("session_"):
            return "session"
        if focus.startswith("family:"):
            return "family"
        if focus.startswith("regime:"):
            return "regime"
        if focus.startswith("session:"):
            return "session"
        return "global"

    @staticmethod
    def _confidence_from_samples(samples: int) -> str:
        if samples >= 8:
            return "high"
        if samples >= 4:
            return "medium"
        return "low"

    @classmethod
    def _sample_note(cls, samples: int) -> str:
        confidence = cls._confidence_from_samples(samples)
        if confidence == "high":
            return "repeat evidence is present"
        if confidence == "medium":
            return "usable evidence, but still limited"
        return "sample is thin; treat this as advisory context only"

    @staticmethod
    def _bucket_row(store: dict[str, Any]) -> dict[str, Any]:
        return {
            "funnel": dict(store.get("funnel") or {}),
            "focus_items": list(store.get("focus_items") or []),
            "outcome_signals": list(store.get("outcome_signals") or []),
            "softening_items": list(store.get("softening_items") or []),
            "promotion_items": list(store.get("promotion_items") or []),
        }

    @staticmethod
    def _funnel_blocking_signals(row: dict[str, Any]) -> list[str]:
        signals: list[str] = []
        runtime_candidates = int(row.get("runtime_candidates", 0) or 0)
        accept_rate = float(row.get("accept_rate", 0.0) or 0.0)
        closed = int(row.get("closed", 0) or 0)
        profitable_rate = float(row.get("profitable_rate_from_closed", 0.0) or 0.0)
        baseline_cost_profitable_rate = float(row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)

        if runtime_candidates >= 4 and accept_rate <= 0.25:
            signals.append("low_accept_rate")
        if closed >= 3 and profitable_rate <= 0.4:
            signals.append("low_closed_profit_rate")
        if closed >= 3 and baseline_cost_profitable_rate <= 0.3:
            signals.append("low_post_cost_conversion")
        return signals

    @staticmethod
    def _focus_blocking_signals(focus_items: list[dict[str, Any]]) -> list[str]:
        signals: list[str] = []
        for row in focus_items:
            focus = str(row.get("focus") or "")
            if focus in {
                "family_information_failure",
                "family_forced_exit",
                "regime_negative_ev",
                "session_negative_ev",
            }:
                signals.append(f"focus:{focus}")
        return signals

    @staticmethod
    def _signal_bucket_key(row: dict[str, Any]) -> tuple[str, str]:
        return str(row.get("axis") or "global"), str(row.get("bucket") or "unknown")

    def generate(
        self,
        *,
        score_to_outcome_funnel: dict[str, Any] | None,
        execution_degradation_advisory: dict[str, Any] | None,
        performance_decomposition_summary: dict[str, Any] | None,
        alpha_research_evidence_summary: dict[str, Any] | None,
        softening_candidate_review: dict[str, Any] | None,
        promotion_watchlist: dict[str, Any] | None,
    ) -> dict[str, Any]:
        funnel_payload = dict(score_to_outcome_funnel or {})
        degradation_payload = dict(execution_degradation_advisory or {})
        performance_payload = dict(performance_decomposition_summary or {})
        evidence_payload = dict(alpha_research_evidence_summary or {})
        softening_payload = dict(softening_candidate_review or {})
        promotion_payload = dict(promotion_watchlist or {})

        if not any(
            [
                funnel_payload,
                degradation_payload,
                performance_payload,
                evidence_payload,
                softening_payload,
                promotion_payload,
            ]
        ):
            return {
                "available": False,
                "coverage_note": "mode advisory unavailable",
                "family": [],
                "regime": [],
                "session": [],
            }

        grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "funnel": {},
                "focus_items": [],
                "outcome_signals": [],
                "softening_items": [],
                "promotion_items": [],
            }
        )

        decomposition = dict(funnel_payload.get("decomposition") or {})
        for axis in ("family", "regime", "session"):
            for row in list(decomposition.get(axis) or []):
                grouped[(axis, str(row.get("key") or "unknown"))]["funnel"] = dict(row)

        evidence_focus_summary = dict(evidence_payload.get("focus_alignment_summary") or {})
        for row in list(evidence_focus_summary.get("focus_items") or []):
            axis = self._focus_axis(str(row.get("focus") or ""))
            if axis not in {"family", "regime", "session"}:
                continue
            grouped[(axis, str(row.get("bucket") or "unknown"))]["focus_items"].append(dict(row))

        outcome_summary = dict(evidence_payload.get("outcome_alignment_summary") or {})
        for row in list(outcome_summary.get("alignment_signals") or []):
            axis = str(row.get("axis") or "global")
            if axis not in {"family", "regime", "session"}:
                continue
            grouped[(axis, str(row.get("bucket") or "unknown"))]["outcome_signals"].append(dict(row))

        for row in list(softening_payload.get("review_items") or []):
            axis = str(row.get("axis") or "global")
            if axis not in {"family", "regime", "session"}:
                continue
            grouped[(axis, str(row.get("bucket") or "unknown"))]["softening_items"].append(dict(row))

        for row in list(promotion_payload.get("watch_items") or []):
            axis = self._focus_axis(str(row.get("focus") or ""))
            if axis not in {"family", "regime", "session"}:
                continue
            grouped[(axis, str(row.get("bucket") or "unknown"))]["promotion_items"].append(dict(row))

        for row in list(performance_payload.get("tuning_focus") or []):
            axis = self._focus_axis(str(row.get("focus") or ""))
            if axis not in {"family", "regime", "session"}:
                continue
            grouped[(axis, str(row.get("bucket") or "unknown"))]["focus_items"].append(dict(row))

        degradation_status = str(degradation_payload.get("status") or "healthy")
        severity_rank = {
            "research_only": 3,
            "watch": 2,
            "promotion_watch": 1,
            "keep_current_mode": 0,
        }
        confidence_rank = {"high": 2, "medium": 1, "low": 0}

        rows_by_axis: dict[str, list[dict[str, Any]]] = {"family": [], "regime": [], "session": []}
        for (axis, bucket), raw in grouped.items():
            payload = self._bucket_row(raw)
            funnel_row = dict(payload.get("funnel") or {})
            focus_items = list(payload.get("focus_items") or [])
            outcome_signals = list(payload.get("outcome_signals") or [])
            softening_items = list(payload.get("softening_items") or [])
            promotion_items = list(payload.get("promotion_items") or [])

            support: list[str] = []
            blocking: list[str] = []
            state = "keep_current_mode"
            why = "no strong evidence to change the current operating interpretation"

            samples = max(
                int(funnel_row.get("runtime_candidates", 0) or 0),
                int(funnel_row.get("submitted", 0) or 0),
                int(funnel_row.get("closed", 0) or 0),
                max((int(item.get("matched_candidates", 0) or 0) for item in promotion_items), default=0),
                max((int(item.get("matched_candidates", 0) or 0) for item in outcome_signals), default=0),
            )
            confidence = self._confidence_from_samples(samples)
            sample_note = self._sample_note(samples)

            funnel_blocking = self._funnel_blocking_signals(funnel_row)
            focus_blocking = self._focus_blocking_signals(focus_items)
            blocking.extend(funnel_blocking)
            blocking.extend(focus_blocking)

            top_softening = dict((softening_items[:1] or [{}])[0])
            top_promotion = dict((promotion_items[:1] or [{}])[0])

            if top_softening:
                state = "research_only"
                support.append(
                    f"softening_review:{top_softening.get('review_priority') or 'unknown'}"
                )
                why = "quality near-miss cluster needs research review before broader use"
                if str(top_softening.get("confidence") or ""):
                    confidence = str(top_softening.get("confidence"))
                if str(top_softening.get("sample_note") or ""):
                    sample_note = str(top_softening.get("sample_note"))

            promotion_ready = (
                bool(top_promotion)
                and top_promotion.get("not_ready_reason") in {None, "", "none"}
                and str(top_promotion.get("confidence") or confidence) in {"high", "medium"}
            )
            if promotion_ready:
                state = "promotion_watch"
                support.append("promotion_watchlist")
                why = "shadow progression evidence exists; keep watching before any rollout change"
                confidence = str(top_promotion.get("confidence") or confidence)
                sample_note = str(top_promotion.get("sample_note") or sample_note)

            degradation_applies = degradation_status in {"watch", "manual_review"} and (
                bool(funnel_blocking) or bool(focus_blocking) or bool(outcome_signals)
            )
            if degradation_applies:
                blocking.append(f"execution_degradation:{degradation_status}")
                if degradation_status == "manual_review" or state != "promotion_watch":
                    state = "watch" if state == "keep_current_mode" else state
                    if state == "promotion_watch":
                        state = "watch"
                if state == "keep_current_mode":
                    state = "watch"
                why = "execution or post-cost outcome signals are degrading for this bucket"

            if state == "promotion_watch" and degradation_status == "manual_review":
                state = "watch"
                why = "execution degradation is too elevated to treat this bucket as promotion-watch"

            if state == "research_only" and degradation_status == "manual_review":
                blocking.append("execution_degradation:manual_review")

            support.extend(
                f"outcome_alignment:{str(row.get('alignment_strength') or 'low')}"
                for row in outcome_signals[:2]
            )

            row = {
                "axis": axis,
                "bucket": bucket,
                "advisory_state": state,
                "why": why,
                "supporting_signals": list(dict.fromkeys(support)),
                "blocking_signals": list(dict.fromkeys(blocking)),
                "confidence": confidence,
                "sample_note": sample_note,
                "advisory_only": True,
            }
            rows_by_axis[axis].append(row)

        for axis, rows in rows_by_axis.items():
            rows.sort(
                key=lambda row: (
                    -int(severity_rank.get(str(row.get("advisory_state") or "keep_current_mode"), 0)),
                    -int(confidence_rank.get(str(row.get("confidence") or "low"), 0)),
                    str(row.get("bucket") or ""),
                )
            )
            rows_by_axis[axis] = rows[:5]

        return {
            "available": True,
            "coverage_note": (
                "mode advisory is evidence-backed but advisory only; it does not change rollout policy, "
                "approval semantics, or live execution controls"
            ),
            "family": rows_by_axis["family"],
            "regime": rows_by_axis["regime"],
            "session": rows_by_axis["session"],
        }
