from __future__ import annotations

from typing import Any


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_BLOCKING_ROLLOUT_STATES = {"reduce", "research_only"}
_BLOCKING_LIFECYCLE_STATES = {"research", "degraded", "retired"}
_READY_EXECUTION_STAGES = {"dry_run_execution", "semi_auto_candidate"}


class BContinuationActivationService:
    _TARGET_FAMILY = "trend_continuation"

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

    @staticmethod
    def _normalize_confidence(value: Any) -> str:
        confidence = str(value or "low").strip().lower()
        return confidence if confidence in _CONFIDENCE_RANK else "low"

    def _family_outcome_row(self, *, score_to_outcome_funnel: dict[str, Any]) -> dict[str, Any]:
        rows = {
            str(row.get("key") or "unknown").strip().lower(): dict(row)
            for row in self._rows(dict(score_to_outcome_funnel.get("decomposition") or {}), "family")
        }
        return dict(rows.get(self._TARGET_FAMILY) or {})

    def _family_execution_row(self, *, family_execution_degradation_advisory: dict[str, Any]) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(family_execution_degradation_advisory, "families")
        }
        return dict(rows.get(self._TARGET_FAMILY) or {})

    def _reopen_row(self, *, promotion_reopen_queue: dict[str, Any]) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(promotion_reopen_queue, "reopen_queue")
        }
        return dict(rows.get(self._TARGET_FAMILY) or {})

    def _resolve_rollout_state(
        self,
        *,
        rollout_recommendation: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        promotion_governance: dict[str, Any],
    ) -> str:
        if str(rollout_recommendation.get("family") or "").strip().lower() == self._TARGET_FAMILY:
            state = str(rollout_recommendation.get("recommendation") or "").strip().lower()
            if state:
                return state
        for payload in (strategy_lifecycle, promotion_governance):
            if str(payload.get("family") or "").strip().lower() != self._TARGET_FAMILY:
                continue
            source_summary = dict(payload.get("source_summary") or {})
            state = str(source_summary.get("rollout_recommendation") or "").strip().lower()
            if state:
                return state
        return "unavailable"

    def _resolve_lifecycle_state(
        self,
        *,
        strategy_lifecycle: dict[str, Any],
        promotion_governance: dict[str, Any],
        promotion_decision_brief: dict[str, Any],
    ) -> str:
        if str(strategy_lifecycle.get("family") or "").strip().lower() == self._TARGET_FAMILY:
            state = str(strategy_lifecycle.get("state") or "").strip().lower()
            if state:
                return state
        for payload in (promotion_decision_brief, promotion_governance):
            if str(payload.get("family") or "").strip().lower() != self._TARGET_FAMILY:
                continue
            source_summary = dict(payload.get("source_summary") or {})
            state = str(source_summary.get("lifecycle_state") or "").strip().lower()
            if state:
                return state
        return "unavailable"

    def _resolve_family_execution_status(
        self,
        *,
        family_execution_degradation_advisory: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
        promotion_governance: dict[str, Any],
        promotion_decision_brief: dict[str, Any],
        promotion_clearance_tracker: dict[str, Any],
    ) -> str:
        row = self._family_execution_row(
            family_execution_degradation_advisory=family_execution_degradation_advisory
        )
        status = str(row.get("status") or "").strip().lower()
        if status in {"healthy", "watch", "manual_review"}:
            return status
        for payload in (
            promotion_decision_brief,
            promotion_clearance_tracker,
            promotion_governance,
            strategy_lifecycle,
        ):
            if str(payload.get("family") or "").strip().lower() != self._TARGET_FAMILY:
                continue
            source_summary = dict(payload.get("source_summary") or {})
            status = str(source_summary.get("family_execution_status") or "").strip().lower()
            if status in {"healthy", "watch", "manual_review"}:
                return status
        return "unavailable"

    @staticmethod
    def _overlay_from_multi_strategy(multi_strategy_ab: dict[str, Any]) -> dict[str, Any]:
        return dict(multi_strategy_ab.get("b_cluster") or {})

    @staticmethod
    def _overlay_from_row(row: dict[str, Any]) -> dict[str, Any]:
        overlay = dict(row.get("multi_strategy_overlay") or {})
        if str(overlay.get("cluster") or "").strip().lower() == "b_continuation":
            return overlay
        if str(row.get("strategy_cluster") or "").strip().lower() == "b_continuation":
            return {
                "available": True,
                "cluster": "b_continuation",
                "mode": row.get("strategy_mode"),
                "strategy_cluster_status": row.get("strategy_cluster_status"),
                "summary": str(row.get("expected_summary") or ""),
                "reason_codes": [],
                "guardrail_reasons": [],
                "live_eligible": False,
                "guarded": True,
            }
        return {}

    @staticmethod
    def _mode_from_overlay(overlay: dict[str, Any], fallback: Any) -> str:
        text = str(overlay.get("mode") or fallback or "A_ONLY").strip().upper()
        return text if text in {"A_ONLY", "A_PLUS_B", "RESEARCH"} else "A_ONLY"

    def _reopen_action(self, *, promotion_reopen_queue: dict[str, Any]) -> str:
        row = self._reopen_row(promotion_reopen_queue=promotion_reopen_queue)
        action = str(row.get("reopen_action") or "").strip().lower()
        if action:
            return action
        if str(promotion_reopen_queue.get("headline_family") or "").strip().lower() == self._TARGET_FAMILY:
            action = str(promotion_reopen_queue.get("top_reopen_action") or "").strip().lower()
            if action:
                return action
        return "none"

    def _clearance_state(
        self,
        *,
        promotion_clearance_tracker: dict[str, Any],
        promotion_reopen_queue: dict[str, Any],
        promotion_decision_brief: dict[str, Any],
    ) -> str:
        if str(promotion_clearance_tracker.get("family") or "").strip().lower() == self._TARGET_FAMILY:
            state = str(promotion_clearance_tracker.get("clearance_state") or "").strip().lower()
            if state:
                return state
        row = self._reopen_row(promotion_reopen_queue=promotion_reopen_queue)
        state = str(row.get("clearance_state") or "").strip().lower()
        if state:
            return state
        if str(promotion_decision_brief.get("family") or "").strip().lower() == self._TARGET_FAMILY:
            source_summary = dict(promotion_decision_brief.get("source_summary") or {})
            state = str(source_summary.get("clearance_state") or "").strip().lower()
            if state:
                return state
        return "unknown"

    def _build_payload(
        self,
        *,
        mode: str,
        overlay: dict[str, Any],
        family_closed: int,
        execution_status: str,
        rollout_state: str,
        lifecycle_state: str,
        governance_state: str,
        clearance_state: str,
        reopen_action: str,
        brief_state: str,
        execution_stage: str,
        positive_state: str,
    ) -> dict[str, Any]:
        cluster_status = str(overlay.get("strategy_cluster_status") or "overlay_unavailable").strip().lower()
        live_eligible = bool(overlay.get("live_eligible", False))
        guardrail_reasons = self._dedupe(list(overlay.get("guardrail_reasons") or []))
        reason_codes = self._dedupe(
            [
                f"mode:{mode.lower()}",
                f"cluster_status:{cluster_status}",
                *(list(overlay.get("reason_codes") or [])),
            ]
        )
        thin_sample = "b_guardrail:thin_sample" in guardrail_reasons or family_closed < 4
        hard_blockers: list[str] = []
        if execution_status == "manual_review":
            hard_blockers.append("b_activation_block:family_execution_manual_review")
        if rollout_state in _BLOCKING_ROLLOUT_STATES:
            hard_blockers.append(f"b_activation_block:rollout_{rollout_state}")
        if lifecycle_state in _BLOCKING_LIFECYCLE_STATES:
            hard_blockers.append(f"b_activation_block:lifecycle_{lifecycle_state}")
        if clearance_state == "blocked":
            hard_blockers.append("b_activation_block:clearance_blocked")
        if brief_state == "clearance_required":
            hard_blockers.append("b_activation_block:decision_brief_clearance_required")
        if reopen_action == "continue_clearance":
            hard_blockers.append("b_activation_block:reopen_continue_clearance")
        if execution_stage == "auto_execution_blocked":
            hard_blockers.append("b_activation_block:auto_execution_blocked")

        activation_ready = (
            mode == "A_PLUS_B"
            and cluster_status == "probation_ready"
            and live_eligible
            and not hard_blockers
            and clearance_state == "clearance_ready"
            and reopen_action == "reopen_review"
        ) or (
            mode == "A_PLUS_B"
            and cluster_status == "probation_ready"
            and live_eligible
            and not hard_blockers
            and execution_stage in _READY_EXECUTION_STAGES
        )

        if mode in {"A_ONLY", "RESEARCH"} or cluster_status in {"compare_only", "research_only"}:
            activation_state = "research_only"
            activation_bias = "stay_research"
            confidence = "low"
            summary = (
                "B continuation remains compare-only under the current mode and should stay in research posture."
            )
        elif hard_blockers:
            activation_state = "blocked"
            activation_bias = "clear_guardrails"
            confidence = "medium" if clearance_state == "blocked" or execution_status == "manual_review" else "low"
            summary = (
                "B continuation still has hard first-wave blockers; clear execution, policy, or clearance guardrails "
                "before activation review."
            )
        elif activation_ready:
            activation_state = "activation_ready"
            activation_bias = "consider_first_wave_activation"
            confidence = "high" if execution_stage in _READY_EXECUTION_STAGES else "medium"
            summary = (
                "B continuation has cleared first-wave guardrails and can be reviewed for guarded activation under A_PLUS_B."
            )
        else:
            activation_state = "guarded_probation"
            activation_bias = "continue_guarded_probation"
            confidence = "medium" if positive_state == "expandable" or live_eligible else "low"
            summary = (
                "B continuation is available under A_PLUS_B but should remain guarded probation while first-wave evidence "
                "and guardrails continue to mature."
            )

        reason_codes = self._dedupe(
            [
                f"b_activation:{activation_state}",
                *reason_codes,
                *guardrail_reasons,
                *hard_blockers,
                "b_activation_guardrail:thin_sample" if thin_sample else "",
                f"governance:{governance_state}" if governance_state and governance_state != "unknown" else "",
                f"clearance:{clearance_state}" if clearance_state and clearance_state != "unknown" else "",
                f"reopen:{reopen_action}" if reopen_action and reopen_action != "none" else "",
                f"execution_stage:{execution_stage}" if execution_stage and execution_stage != "unknown" else "",
            ]
        )

        return {
            "available": True,
            "advisory_only": True,
            "family": self._TARGET_FAMILY,
            "activation_state": activation_state,
            "activation_bias": activation_bias,
            "target_mode": mode,
            "confidence": confidence,
            "live_eligible": bool(live_eligible),
            "summary": summary,
            "reason_codes": reason_codes,
            "source_summary": {
                "cluster_status": cluster_status,
                "family_closed": int(family_closed),
                "family_execution_status": execution_status,
                "rollout_recommendation": rollout_state,
                "lifecycle_state": lifecycle_state,
                "governance_state": governance_state,
                "clearance_state": clearance_state,
                "reopen_action": reopen_action,
                "brief_state": brief_state,
                "execution_stage": execution_stage,
                "positive_expansion_state": positive_state,
                "thin_sample": bool(thin_sample),
                "guardrail_reasons": guardrail_reasons,
            },
        }

    def generate(
        self,
        *,
        multi_strategy_ab: dict[str, Any] | None,
        score_to_outcome_funnel: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        rollout_recommendation: dict[str, Any] | None,
        strategy_lifecycle: dict[str, Any] | None,
        promotion_governance: dict[str, Any] | None,
        promotion_clearance_tracker: dict[str, Any] | None,
        promotion_reopen_queue: dict[str, Any] | None,
        promotion_decision_brief: dict[str, Any] | None,
        auto_promotion_rollout_execution: dict[str, Any] | None,
        positive_evidence_expansion: dict[str, Any] | None,
    ) -> dict[str, Any]:
        multi_strategy_payload = self._dict(multi_strategy_ab)
        score_payload = self._dict(score_to_outcome_funnel)
        family_execution_payload = self._dict(family_execution_degradation_advisory)
        rollout_payload = self._dict(rollout_recommendation)
        lifecycle_payload = self._dict(strategy_lifecycle)
        governance_payload = self._dict(promotion_governance)
        clearance_payload = self._dict(promotion_clearance_tracker)
        reopen_payload = self._dict(promotion_reopen_queue)
        decision_payload = self._dict(promotion_decision_brief)
        auto_execution_payload = self._dict(auto_promotion_rollout_execution)
        positive_payload = self._dict(positive_evidence_expansion)

        overlay = self._overlay_from_multi_strategy(multi_strategy_payload)
        if not any(
            [
                overlay,
                score_payload,
                family_execution_payload,
                rollout_payload,
                lifecycle_payload,
                governance_payload,
                clearance_payload,
                reopen_payload,
                decision_payload,
                auto_execution_payload,
                positive_payload,
            ]
        ):
            return {"available": False, "advisory_only": True, "summary": "b continuation activation unavailable"}

        mode = self._mode_from_overlay(overlay, multi_strategy_payload.get("mode"))
        family_row = self._family_outcome_row(score_to_outcome_funnel=score_payload)
        execution_status = self._resolve_family_execution_status(
            family_execution_degradation_advisory=family_execution_payload,
            strategy_lifecycle=lifecycle_payload,
            promotion_governance=governance_payload,
            promotion_decision_brief=decision_payload,
            promotion_clearance_tracker=clearance_payload,
        )
        rollout_state = self._resolve_rollout_state(
            rollout_recommendation=rollout_payload,
            strategy_lifecycle=lifecycle_payload,
            promotion_governance=governance_payload,
        )
        lifecycle_state = self._resolve_lifecycle_state(
            strategy_lifecycle=lifecycle_payload,
            promotion_governance=governance_payload,
            promotion_decision_brief=decision_payload,
        )
        governance_state = (
            str(governance_payload.get("state") or "unknown").strip().lower()
            if str(governance_payload.get("family") or "").strip().lower() == self._TARGET_FAMILY
            else "unknown"
        )
        clearance_state = self._clearance_state(
            promotion_clearance_tracker=clearance_payload,
            promotion_reopen_queue=reopen_payload,
            promotion_decision_brief=decision_payload,
        )
        reopen_action = self._reopen_action(promotion_reopen_queue=reopen_payload)
        brief_state = (
            str(decision_payload.get("brief_state") or "observe_case").strip().lower()
            if str(decision_payload.get("family") or "").strip().lower() == self._TARGET_FAMILY
            else "observe_case"
        )
        execution_stage = (
            str(auto_execution_payload.get("execution_stage") or "unknown").strip().lower()
            if str(auto_execution_payload.get("target_family") or "").strip().lower() == self._TARGET_FAMILY
            else "unknown"
        )
        positive_state = (
            str(positive_payload.get("state") or "unknown").strip().lower()
            if str(positive_payload.get("family") or "").strip().lower() == self._TARGET_FAMILY
            else "unknown"
        )

        return self._build_payload(
            mode=mode,
            overlay=overlay,
            family_closed=int(family_row.get("closed", 0) or 0),
            execution_status=execution_status,
            rollout_state=rollout_state,
            lifecycle_state=lifecycle_state,
            governance_state=governance_state,
            clearance_state=clearance_state,
            reopen_action=reopen_action,
            brief_state=brief_state,
            execution_stage=execution_stage,
            positive_state=positive_state,
        )

    def annotate_rows(
        self,
        rows: list[dict[str, Any]] | None,
        *,
        outcome_inputs_by_symbol: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        annotated: list[dict[str, Any]] = []
        inputs_by_symbol = {str(key).upper(): dict(value or {}) for key, value in dict(outcome_inputs_by_symbol or {}).items()}
        for row in list(rows or []):
            item = dict(row)
            if str(item.get("strategy_family") or "").strip().lower() != self._TARGET_FAMILY:
                annotated.append(item)
                continue
            overlay = self._overlay_from_row(item)
            if not overlay:
                annotated.append(item)
                continue

            symbol_inputs = dict(inputs_by_symbol.get(str(item.get("symbol") or "").upper()) or {})
            summary = self.generate(
                multi_strategy_ab={
                    "mode": item.get("strategy_mode"),
                    "b_cluster": overlay,
                },
                score_to_outcome_funnel=dict(symbol_inputs.get("score_to_outcome_funnel_summary") or {}),
                family_execution_degradation_advisory=dict(
                    symbol_inputs.get("family_execution_degradation_advisory_summary") or {}
                ),
                rollout_recommendation=dict(symbol_inputs.get("rollout_recommendation_summary") or {}),
                strategy_lifecycle={},
                promotion_governance={},
                promotion_clearance_tracker={},
                promotion_reopen_queue={},
                promotion_decision_brief={},
                auto_promotion_rollout_execution={},
                positive_evidence_expansion={},
            )
            item["b_continuation_activation"] = summary if summary.get("available", False) else None
            annotated.append(item)
        return annotated
