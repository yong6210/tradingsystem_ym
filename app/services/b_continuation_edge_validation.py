from __future__ import annotations

from typing import Any


class BContinuationEdgeValidationService:
    _B_FAMILY = "trend_continuation"
    _A_FAMILY = "sweep_reversal"
    _B_CLUSTER = "b_continuation"

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
    def _family_row(cls, score_to_outcome_funnel: dict[str, Any], family: str) -> dict[str, Any]:
        decomposition = cls._dict(score_to_outcome_funnel.get("decomposition"))
        for row in cls._rows(decomposition, "family"):
            if str(row.get("key") or "").strip().lower() == family:
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
            return "thin_sample"
        if closed >= 8:
            return "mature_sample"
        return "usable_sample"

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
        row = dict(rows.get(cls._B_FAMILY) or {})
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
        family_focus = dict(bucket_payload.get("family_focus") or {})
        top_axis = str(bucket_payload.get("top_condition_axis") or "").strip().lower()
        top_bucket = str(dict(bucket_payload.get("top_condition_bucket") or {}).get("key") or "").strip().lower()
        if str(family_focus.get("key") or "").strip().lower() == cls._B_FAMILY and top_axis and top_bucket:
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
            return "family", cls._B_FAMILY
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
    def _activation_context(b_continuation_activation: dict[str, Any]) -> tuple[str, str, str]:
        payload = dict(b_continuation_activation or {})
        return (
            str(payload.get("activation_state") or "unavailable").strip().lower(),
            str(payload.get("activation_bias") or "").strip().lower(),
            str(payload.get("target_mode") or "").strip().upper(),
        )

    @staticmethod
    def _cluster_balance_context(strategy_cluster_balance: dict[str, Any]) -> tuple[str, str]:
        payload = dict(strategy_cluster_balance or {})
        return (
            str(payload.get("balance_state") or "unknown").strip().lower(),
            str(payload.get("balance_bias") or "").strip().lower(),
        )

    @classmethod
    def _allocator_context(cls, capital_allocator: dict[str, Any]) -> tuple[str, str, str]:
        payload = dict(capital_allocator or {})
        family_focus = str(payload.get("family_focus") or "").strip().lower()
        capital_pressure = str(payload.get("capital_pressure") or "neutral").strip().lower()
        tier = "neutral"
        for row in list(payload.get("family_weights") or []):
            normalized = dict(row)
            if str(normalized.get("family") or "").strip().lower() == cls._B_FAMILY:
                tier = str(normalized.get("tier") or "neutral").strip().lower()
                break
        return family_focus, capital_pressure, tier if tier in {"boost", "reduce"} else "neutral"

    @classmethod
    def _a_b_correlation_proxy(
        cls,
        *,
        sample_state: str,
        balance_state: str,
        allocator_focus: str,
        capital_pressure: str,
    ) -> str:
        if sample_state == "thin_sample" or balance_state == "research_only_mix":
            return "unknown_proxy"
        if balance_state == "balanced_mix":
            return "low_overlap_proxy"
        if balance_state == "guarded_rebalance":
            return "mixed_overlap_proxy"
        if (
            balance_state == "a_concentrated"
            and allocator_focus == cls._B_FAMILY
            and capital_pressure == "overallocated_negative"
        ):
            return "high_overlap_proxy"
        return "mixed_overlap_proxy"

    @staticmethod
    def _drawdown_contribution_state(
        *,
        sample_state: str,
        family_post_cost_rate: float,
        balance_state: str,
        allocator_focus: str,
        capital_pressure: str,
    ) -> str:
        if sample_state == "thin_sample":
            return "drawdown_unknown"
        if allocator_focus == BContinuationEdgeValidationService._B_FAMILY and capital_pressure == "overallocated_negative":
            return "drawdown_additive"
        if family_post_cost_rate <= 0.3:
            return "drawdown_additive"
        if (
            family_post_cost_rate >= 0.5
            and capital_pressure == "underallocated_positive"
            and balance_state in {"guarded_rebalance", "balanced_mix"}
        ):
            return "drawdown_buffering"
        return "drawdown_neutral"

    @staticmethod
    def _diversification_state(
        *,
        family_post_cost_rate: float,
        capital_pressure: str,
        a_b_correlation_proxy: str,
        drawdown_contribution_state: str,
    ) -> str:
        if drawdown_contribution_state == "drawdown_additive":
            return "drawdown_additive"
        if a_b_correlation_proxy == "high_overlap_proxy":
            return "correlation_heavy"
        if (
            family_post_cost_rate >= 0.5
            and a_b_correlation_proxy in {"low_overlap_proxy", "mixed_overlap_proxy"}
            and capital_pressure != "overallocated_negative"
        ):
            return "diversifying"
        return "unclear_diversification"

    @staticmethod
    def _is_b_deterioration_focus(*, focus: str, bucket: str) -> bool:
        normalized_focus = str(focus or "").strip().lower()
        normalized_bucket = str(bucket or "").strip().lower()
        if normalized_focus == "post_cost_ev_deterioration":
            return normalized_bucket in {"", "global", "trend_continuation", "b_continuation"}
        return normalized_bucket in {"trend_continuation", "b_continuation"} and normalized_focus in {
            "family_information_failure",
            "family_forced_exit_deterioration",
        }

    @staticmethod
    def _confidence(
        *,
        edge_state: str,
        sample_state: str,
        family_execution_confidence: str,
        a_b_correlation_proxy: str,
        drawdown_contribution_state: str,
        weakest_axis: str,
    ) -> str:
        if (
            edge_state == "validated_edge"
            and sample_state == "mature_sample"
            and family_execution_confidence in {"medium", "high"}
            and a_b_correlation_proxy in {"low_overlap_proxy", "mixed_overlap_proxy"}
            and drawdown_contribution_state in {"drawdown_buffering", "drawdown_neutral"}
            and not weakest_axis
        ):
            return "high"
        if edge_state in {"validated_edge", "fragile_edge"} and sample_state in {"usable_sample", "mature_sample"}:
            return "medium"
        return "low"

    @staticmethod
    def _validation_bias(edge_state: str) -> str:
        return {
            "validated_edge": "support_guarded_activation",
            "fragile_edge": "monitor_diversification",
            "insufficient_edge": "reduce_b_confidence",
            "insufficient_sample": "gather_more_evidence",
        }.get(edge_state, "gather_more_evidence")

    @staticmethod
    def _summary(
        *,
        edge_state: str,
        family_post_cost_rate: float,
        diversification_state: str,
        drawdown_contribution_state: str,
        a_b_correlation_proxy: str,
        weakest_axis: str,
        weakest_bucket: str,
    ) -> str:
        family = BContinuationEdgeValidationService._B_FAMILY
        if edge_state == "validated_edge":
            return (
                f"family={family} has usable post-cost support and still offers diversification value under the current "
                f"mix; keep B confidence guarded but constructive. baseline_cost_profitable_rate_from_closed={family_post_cost_rate:.4f}."
            )
        if edge_state == "fragile_edge":
            if diversification_state == "correlation_heavy":
                return (
                    f"family={family} still has some post-cost support, but diversification remains fragile because the "
                    "current A/B overlap proxy is still heavy."
                )
            if drawdown_contribution_state == "drawdown_additive":
                return (
                    f"family={family} still has some usable evidence, but current allocator pressure implies B may still "
                    "be adding drawdown rather than buffering it."
                )
            if weakest_axis and weakest_bucket:
                return (
                    f"family={family} still has usable B evidence, but fragility is concentrated in "
                    f"{weakest_axis}:{weakest_bucket}; monitor diversification confidence before treating B as durable."
                )
            if a_b_correlation_proxy == "high_overlap_proxy":
                return (
                    f"family={family} still has some support, but diversification value remains fragile because B is "
                    "still reading as too close to the current A-heavy mix."
                )
            return f"family={family} still shows some usable evidence, but B diversification confidence needs monitoring."
        if edge_state == "insufficient_edge":
            return (
                f"family={family} does not currently show enough post-cost or diversification support to justify strong "
                "B confidence; reduce B confidence while reviewing overlap, drawdown, and execution drift."
            )
        return (
            f"family={family} sample is still too thin to validate post-cost B edge or diversification value; gather "
            "more closed evidence before making stronger claims."
        )

    @classmethod
    def generate(
        cls,
        *,
        score_to_outcome_funnel: dict[str, Any] | None,
        outcome_bucket_granularity: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        alpha_research_pipeline: dict[str, Any] | None,
        b_continuation_activation: dict[str, Any] | None,
        multi_strategy_ab_summary: dict[str, Any] | None,
        strategy_cluster_balance: dict[str, Any] | None,
        capital_allocator: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        funnel_payload = cls._dict(score_to_outcome_funnel)
        if not funnel_payload:
            return None

        family_row = cls._family_row(funnel_payload, cls._B_FAMILY)
        if not family_row:
            return {
                "available": False,
                "advisory_only": True,
                "raw_family": cls._B_FAMILY,
                "strategy_cluster": cls._B_CLUSTER,
                "summary": "B continuation edge validation unavailable; raw trend_continuation family row is missing",
            }

        a_reference_row = cls._family_row(funnel_payload, cls._A_FAMILY)
        closed = int(family_row.get("closed", 0) or 0)
        family_post_cost_rate = float(family_row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
        a_reference_post_cost_rate = (
            float(a_reference_row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
            if a_reference_row
            else None
        )
        post_cost_gap_vs_a = (
            round(family_post_cost_rate - a_reference_post_cost_rate, 4)
            if a_reference_post_cost_rate is not None
            else None
        )
        sample_state = cls._sample_state(closed)
        family_execution_status, family_execution_confidence = cls._family_execution_state(
            family_execution_degradation_advisory=cls._dict(family_execution_degradation_advisory)
        )
        weakest_axis, weakest_bucket = cls._weakest_axis(
            outcome_bucket_granularity=cls._dict(outcome_bucket_granularity),
            score_to_outcome_funnel=funnel_payload,
            family_row=family_row,
        )
        research_focus, research_bucket, research_confidence = cls._research_focus(cls._dict(alpha_research_pipeline))
        activation_state, activation_bias, target_mode = cls._activation_context(cls._dict(b_continuation_activation))
        balance_state, balance_bias = cls._cluster_balance_context(cls._dict(strategy_cluster_balance))
        allocator_focus, capital_pressure, allocator_tier = cls._allocator_context(cls._dict(capital_allocator))
        a_b_correlation_proxy = cls._a_b_correlation_proxy(
            sample_state=sample_state,
            balance_state=balance_state,
            allocator_focus=allocator_focus,
            capital_pressure=capital_pressure,
        )
        drawdown_contribution_state = cls._drawdown_contribution_state(
            sample_state=sample_state,
            family_post_cost_rate=family_post_cost_rate,
            balance_state=balance_state,
            allocator_focus=allocator_focus,
            capital_pressure=capital_pressure,
        )
        diversification_state = cls._diversification_state(
            family_post_cost_rate=family_post_cost_rate,
            capital_pressure=capital_pressure,
            a_b_correlation_proxy=a_b_correlation_proxy,
            drawdown_contribution_state=drawdown_contribution_state,
        )

        if sample_state == "thin_sample":
            edge_state = "insufficient_sample"
        elif (
            family_post_cost_rate <= 0.3
            or family_execution_status == "manual_review"
            or (
                diversification_state == "drawdown_additive"
                and a_b_correlation_proxy == "high_overlap_proxy"
            )
            or (
                cls._is_b_deterioration_focus(focus=research_focus, bucket=research_bucket)
                and family_post_cost_rate < 0.5
            )
        ):
            edge_state = "insufficient_edge"
        elif (
            family_post_cost_rate < 0.5
            or family_execution_status == "watch"
            or a_b_correlation_proxy == "high_overlap_proxy"
            or drawdown_contribution_state == "drawdown_additive"
            or diversification_state == "correlation_heavy"
            or bool(weakest_axis)
            or cls._is_b_deterioration_focus(focus=research_focus, bucket=research_bucket)
        ):
            edge_state = "fragile_edge"
        else:
            edge_state = "validated_edge"

        validation_bias = cls._validation_bias(edge_state)
        confidence = cls._confidence(
            edge_state=edge_state,
            sample_state=sample_state,
            family_execution_confidence=family_execution_confidence,
            a_b_correlation_proxy=a_b_correlation_proxy,
            drawdown_contribution_state=drawdown_contribution_state,
            weakest_axis=weakest_axis,
        )

        b_cluster = dict(cls._dict(multi_strategy_ab_summary).get("b_cluster") or {})

        return {
            "available": True,
            "advisory_only": True,
            "raw_family": cls._B_FAMILY,
            "strategy_cluster": cls._B_CLUSTER,
            "edge_state": edge_state,
            "validation_bias": validation_bias,
            "sample_state": sample_state,
            "family_post_cost_rate": round(family_post_cost_rate, 4),
            "family_post_cost_ev": None,
            "diversification_state": diversification_state,
            "drawdown_contribution_state": drawdown_contribution_state,
            "a_b_correlation_proxy": a_b_correlation_proxy,
            "weakest_axis": weakest_axis,
            "weakest_bucket": weakest_bucket,
            "confidence": confidence,
            "summary": cls._summary(
                edge_state=edge_state,
                family_post_cost_rate=family_post_cost_rate,
                diversification_state=diversification_state,
                drawdown_contribution_state=drawdown_contribution_state,
                a_b_correlation_proxy=a_b_correlation_proxy,
                weakest_axis=weakest_axis,
                weakest_bucket=weakest_bucket,
            ),
            "reason_codes": cls._dedupe(
                [
                    f"b_edge:{edge_state}",
                    f"sample:{sample_state}",
                    f"raw_family:{cls._B_FAMILY}",
                    f"strategy_cluster:{cls._B_CLUSTER}",
                    (
                        f"family_execution:{family_execution_status}"
                        if family_execution_status != "unavailable"
                        else ""
                    ),
                    f"diversification:{diversification_state}",
                    f"drawdown:{drawdown_contribution_state}",
                    f"correlation_proxy:{a_b_correlation_proxy}",
                    f"weakest_axis:{weakest_axis}" if weakest_axis else "",
                    f"weakest_bucket:{weakest_bucket}" if weakest_bucket else "",
                    f"activation_state:{activation_state}" if activation_state and activation_state != "unavailable" else "",
                    f"balance_state:{balance_state}" if balance_state and balance_state != "unknown" else "",
                    f"allocator_tier:{allocator_tier}" if allocator_tier != "neutral" else "",
                    f"capital_pressure:{capital_pressure}" if capital_pressure != "neutral" else "",
                    f"research_focus:{research_focus}" if research_focus else "",
                ]
            ),
            "source_summary": {
                "raw_family_anchor": cls._B_FAMILY,
                "strategy_cluster": cls._B_CLUSTER,
                "family_closed": closed,
                "family_post_cost_rate": round(family_post_cost_rate, 4),
                "a_reference_post_cost_rate": (
                    round(a_reference_post_cost_rate, 4) if a_reference_post_cost_rate is not None else None
                ),
                "post_cost_gap_vs_a": post_cost_gap_vs_a,
                "family_execution_status": family_execution_status,
                "family_execution_confidence": family_execution_confidence,
                "activation_state": activation_state or None,
                "activation_bias": activation_bias or None,
                "target_mode": target_mode or None,
                "balance_state": balance_state or None,
                "balance_bias": balance_bias or None,
                "allocator_focus": allocator_focus or None,
                "allocator_tier": allocator_tier,
                "capital_pressure": capital_pressure,
                "weakest_axis": weakest_axis or None,
                "weakest_bucket": weakest_bucket or None,
                "alpha_research_focus": research_focus or None,
                "alpha_research_bucket": research_bucket or None,
                "alpha_research_confidence": research_confidence,
                "b_cluster_status": str(b_cluster.get("strategy_cluster_status") or "") or None,
            },
        }
