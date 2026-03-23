from __future__ import annotations

from typing import Any

from app.services.outcome_control_trace import build_outcome_control_trace, summarize_outcome_control_trace


class AStrategyPostCostEdgeValidationService:
    _A_FAMILY = "sweep_reversal"

    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _rows(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
        return [dict(item) for item in list(dict(payload or {}).get(key) or [])]

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    @classmethod
    def _family_row(cls, score_to_outcome_funnel: dict[str, Any]) -> dict[str, Any]:
        decomposition = cls._dict(score_to_outcome_funnel.get("decomposition"))
        for row in cls._rows(decomposition, "family"):
            if str(row.get("key") or "").strip().lower() == cls._A_FAMILY:
                return dict(row)
        return {}

    @staticmethod
    def _negative_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
        candidates = [
            dict(row)
            for row in rows
            if int(row.get("closed", 0) or 0) >= 4
            and float(row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0) <= 0.3
        ]
        if not candidates:
            return {}
        return min(
            candidates,
            key=lambda row: (
                float(row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0),
                -int(row.get("closed", 0) or 0),
                str(row.get("key") or ""),
            ),
        )

    @staticmethod
    def _sample_state(closed: int) -> str:
        if closed < 4:
            return "thin"
        if closed >= 8:
            return "mature"
        return "usable"

    @classmethod
    def _family_execution_state(
        cls,
        *,
        family_execution_degradation_advisory: dict[str, Any],
    ) -> tuple[str, str]:
        rows = {
            str(row.get("family") or "").strip().lower(): dict(row)
            for row in list(dict(family_execution_degradation_advisory or {}).get("families") or [])
        }
        row = dict(rows.get(cls._A_FAMILY) or {})
        status = str(row.get("status") or "unavailable").lower()
        confidence = str(row.get("confidence") or "low").lower()
        if status not in {"healthy", "watch", "manual_review"}:
            status = "unavailable"
        if confidence not in {"low", "medium", "high"}:
            confidence = "low"
        return status, confidence

    @classmethod
    def _weakest_axis(
        cls,
        *,
        outcome_bucket_granularity: dict[str, Any],
        score_to_outcome_funnel: dict[str, Any],
        family_row: dict[str, Any],
    ) -> tuple[str, str]:
        bucket_payload = dict(outcome_bucket_granularity or {})
        top_axis = str(bucket_payload.get("top_condition_axis") or "").strip().lower()
        top_bucket = str(dict(bucket_payload.get("top_condition_bucket") or {}).get("key") or "").strip().lower()
        if top_axis and top_bucket:
            return top_axis, top_bucket

        decomposition = cls._dict(dict(score_to_outcome_funnel or {}).get("decomposition"))
        regime_negative = cls._negative_row(cls._rows(decomposition, "regime"))
        if regime_negative:
            return "regime", str(regime_negative.get("key") or "").strip().lower()

        session_negative = cls._negative_row(cls._rows(decomposition, "session"))
        if session_negative:
            return "session", str(session_negative.get("key") or "").strip().lower()

        family_rate = float(family_row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
        family_closed = int(family_row.get("closed", 0) or 0)
        if family_closed >= 4 and family_rate <= 0.3:
            return "family", cls._A_FAMILY
        return "", ""

    @staticmethod
    def _research_focus(alpha_research_pipeline: dict[str, Any]) -> tuple[str, str, str]:
        action_summary = dict(dict(alpha_research_pipeline or {}).get("recommended_action_summary") or {})
        focus = str(action_summary.get("focus") or "").strip()
        bucket = str(action_summary.get("bucket") or "").strip()
        confidence = str(action_summary.get("confidence") or "low").lower()
        if confidence not in {"low", "medium", "high"}:
            confidence = "low"
        return focus, bucket, confidence

    @staticmethod
    def _confidence(
        *,
        edge_state: str,
        sample_state: str,
        family_execution_confidence: str,
        approval_penalty_status: str,
        sizing_penalty_tier: str,
        weakest_axis: str,
    ) -> str:
        if (
            edge_state == "validated_edge"
            and sample_state == "mature"
            and family_execution_confidence in {"medium", "high"}
            and approval_penalty_status == "healthy"
            and sizing_penalty_tier == "none"
            and not weakest_axis
        ):
            return "high"
        if edge_state in {"validated_edge", "fragile_edge"} and sample_state in {"usable", "mature"}:
            return "medium"
        return "low"

    @staticmethod
    def _validation_bias(edge_state: str) -> str:
        return {
            "validated_edge": "keep_anchor",
            "fragile_edge": "monitor_fragility",
            "insufficient_edge": "reduce_anchor_confidence",
            "insufficient_sample": "gather_more_evidence",
        }.get(edge_state, "gather_more_evidence")

    @staticmethod
    def _summary(
        *,
        edge_state: str,
        family_post_cost_rate: float,
        weakest_axis: str,
        weakest_bucket: str,
        family_execution_status: str,
        approval_penalty_status: str,
        sizing_penalty_tier: str,
        research_focus: str,
    ) -> str:
        family = AStrategyPostCostEdgeValidationService._A_FAMILY
        if edge_state == "validated_edge":
            return (
                f"family={family} still supports the A anchor on current post-cost evidence; keep anchor confidence "
                f"while continuing routine monitoring. baseline_cost_profitable_rate_from_closed={family_post_cost_rate:.4f}."
            )
        if edge_state == "fragile_edge":
            if weakest_axis and weakest_bucket:
                return (
                    f"family={family} still has usable A-anchor evidence, but fragility is concentrated in "
                    f"{weakest_axis}:{weakest_bucket}; monitor anchor confidence before treating A as fully stable."
                )
            if family_execution_status == "watch":
                return (
                    f"family={family} still has usable post-cost support, but execution drift keeps the anchor in "
                    "monitor-fragility posture."
                )
            if approval_penalty_status == "watch" or sizing_penalty_tier == "soft_clamp":
                return (
                    f"family={family} still has some post-cost support, but approval or sizing controls are already "
                    "softening the anchor posture."
                )
            if research_focus == "post_cost_ev_deterioration":
                return (
                    f"family={family} still has some support, but research is already flagging post-cost deterioration; "
                    "treat the anchor as fragile."
                )
            return f"family={family} still shows some post-cost support, but anchor fragility needs monitoring."
        if edge_state == "insufficient_edge":
            return (
                f"family={family} no longer has enough post-cost support to keep high A-anchor confidence; reduce "
                "anchor confidence while reviewing execution and cost deterioration."
            )
        return (
            f"family={family} sample is still too thin to validate post-cost A-anchor edge; gather more evidence "
            "before treating the anchor as stable."
        )

    @classmethod
    def generate(
        cls,
        *,
        score_to_outcome_funnel: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        mode_advisory: dict[str, Any] | None,
        outcome_bucket_granularity: dict[str, Any] | None,
        alpha_research_pipeline: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        funnel_payload = cls._dict(score_to_outcome_funnel)
        if not funnel_payload:
            return None

        family_row = cls._family_row(funnel_payload)
        if not family_row:
            return {
                "available": False,
                "advisory_only": True,
                "family": cls._A_FAMILY,
                "summary": "A-strategy post-cost edge validation unavailable; raw sweep_reversal family row is missing",
            }

        family_execution_payload = cls._dict(family_execution_degradation_advisory)
        mode_payload = cls._dict(mode_advisory)
        bucket_payload = cls._dict(outcome_bucket_granularity)
        research_payload = cls._dict(alpha_research_pipeline)

        closed = int(family_row.get("closed", 0) or 0)
        family_post_cost_rate = float(family_row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
        historical_payload = cls._dict(funnel_payload.get("historical_execution_outcomes"))
        historical_anchor_rate = float(
            historical_payload.get("baseline_cost_profitable_rate_from_closed", family_post_cost_rate) or 0.0
        )
        sample_state = cls._sample_state(closed)
        family_execution_status, family_execution_confidence = cls._family_execution_state(
            family_execution_degradation_advisory=family_execution_payload
        )
        outcome_control_trace = build_outcome_control_trace(
            execution_degradation_advisory={},
            family_execution_degradation_advisory=family_execution_payload,
            mode_advisory=mode_payload,
            score_to_outcome_funnel=funnel_payload,
        )
        outcome_control_trace_summary = summarize_outcome_control_trace(outcome_control_trace) or {}
        approval_penalty_status = str(outcome_control_trace_summary.get("approval_penalty_status") or "healthy").lower()
        sizing_penalty_tier = str(outcome_control_trace_summary.get("sizing_penalty_tier") or "none").lower()
        weakest_axis, weakest_bucket = cls._weakest_axis(
            outcome_bucket_granularity=bucket_payload,
            score_to_outcome_funnel=funnel_payload,
            family_row=family_row,
        )
        research_focus, research_bucket, research_confidence = cls._research_focus(research_payload)

        if sample_state == "thin":
            edge_state = "insufficient_sample"
        elif (
            family_post_cost_rate <= 0.3
            or historical_anchor_rate <= 0.3
            or family_execution_status == "manual_review"
            or approval_penalty_status in {"manual_review", "blocked"}
            or sizing_penalty_tier == "hard_clamp"
        ):
            edge_state = "insufficient_edge"
        elif (
            family_post_cost_rate < 0.5
            or family_execution_status == "watch"
            or approval_penalty_status == "watch"
            or sizing_penalty_tier == "soft_clamp"
            or bool(weakest_axis)
            or research_focus == "post_cost_ev_deterioration"
        ):
            edge_state = "fragile_edge"
        else:
            edge_state = "validated_edge"

        validation_bias = cls._validation_bias(edge_state)
        confidence = cls._confidence(
            edge_state=edge_state,
            sample_state=sample_state,
            family_execution_confidence=family_execution_confidence,
            approval_penalty_status=approval_penalty_status,
            sizing_penalty_tier=sizing_penalty_tier,
            weakest_axis=weakest_axis,
        )

        return {
            "available": True,
            "advisory_only": True,
            "family": cls._A_FAMILY,
            "edge_state": edge_state,
            "validation_bias": validation_bias,
            "sample_state": sample_state,
            "family_post_cost_rate": round(family_post_cost_rate, 4),
            "family_post_cost_ev": None,
            "weakest_axis": weakest_axis,
            "weakest_bucket": weakest_bucket,
            "confidence": confidence,
            "summary": cls._summary(
                edge_state=edge_state,
                family_post_cost_rate=family_post_cost_rate,
                weakest_axis=weakest_axis,
                weakest_bucket=weakest_bucket,
                family_execution_status=family_execution_status,
                approval_penalty_status=approval_penalty_status,
                sizing_penalty_tier=sizing_penalty_tier,
                research_focus=research_focus,
            ),
            "reason_codes": cls._dedupe(
                [
                    f"a_edge:{edge_state}",
                    f"sample:{sample_state}",
                    f"family:{cls._A_FAMILY}",
                    f"family_execution:{family_execution_status}" if family_execution_status != "unavailable" else "",
                    f"approval_penalty:{approval_penalty_status}" if approval_penalty_status else "",
                    f"sizing_penalty:{sizing_penalty_tier}" if sizing_penalty_tier else "",
                    f"weakest_axis:{weakest_axis}" if weakest_axis else "",
                    f"weakest_bucket:{weakest_bucket}" if weakest_bucket else "",
                    f"research_focus:{research_focus}" if research_focus else "",
                    "historical_anchor_rate:weak" if historical_anchor_rate <= 0.3 and sample_state != "thin" else "",
                ]
            ),
            "source_summary": {
                "raw_family_anchor": cls._A_FAMILY,
                "family_closed": closed,
                "family_post_cost_rate": round(family_post_cost_rate, 4),
                "historical_anchor_rate": round(historical_anchor_rate, 4),
                "family_execution_status": family_execution_status,
                "family_execution_confidence": family_execution_confidence,
                "approval_penalty_status": approval_penalty_status,
                "sizing_penalty_tier": sizing_penalty_tier,
                "weakest_axis": weakest_axis or None,
                "weakest_bucket": weakest_bucket or None,
                "alpha_research_focus": research_focus or None,
                "alpha_research_bucket": research_bucket or None,
                "alpha_research_confidence": research_confidence,
            },
        }
