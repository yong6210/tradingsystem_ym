from __future__ import annotations

from typing import Any


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_ACTIVE_REMEDIATION_ACTIONS = {
    "execution_remediation",
    "policy_remediation",
    "condition_remediation",
}


class AutoPromotionRolloutExecutionService:
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

    def _select_family(
        self,
        *,
        promotion_decision_brief: dict[str, Any],
        promotion_reopen_queue: dict[str, Any],
        promotion_clearance_tracker: dict[str, Any],
        promotion_remediation_queue: dict[str, Any],
        promotion_governance: dict[str, Any],
        rollout_recommendation: dict[str, Any],
    ) -> str:
        candidates = [
            str(promotion_decision_brief.get("family") or "").strip().lower(),
            str(promotion_reopen_queue.get("headline_family") or "").strip().lower(),
            str(promotion_clearance_tracker.get("family") or "").strip().lower(),
            str(promotion_remediation_queue.get("headline_family") or "").strip().lower(),
            str(promotion_governance.get("family") or "").strip().lower(),
            str(rollout_recommendation.get("family") or "").strip().lower(),
        ]
        for family in candidates:
            if family and family != "unknown":
                return family
        return ""

    def _review_row(self, *, promotion_review_queue: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(promotion_review_queue, "review_queue")
        }
        return dict(rows.get(family) or {})

    def _remediation_row(self, *, promotion_remediation_queue: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(promotion_remediation_queue, "remediation_queue")
        }
        return dict(rows.get(family) or {})

    def _reopen_row(self, *, promotion_reopen_queue: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(promotion_reopen_queue, "reopen_queue")
        }
        return dict(rows.get(family) or {})

    def _family_execution_status(
        self,
        *,
        family_execution_degradation_advisory: dict[str, Any],
        family: str,
        promotion_governance: dict[str, Any],
        promotion_decision_brief: dict[str, Any],
        promotion_clearance_tracker: dict[str, Any],
    ) -> str:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(family_execution_degradation_advisory, "families")
        }
        row = dict(rows.get(family) or {})
        status = str(row.get("status") or "").lower()
        if status in {"healthy", "watch", "manual_review"}:
            return status

        for payload in (promotion_decision_brief, promotion_clearance_tracker, promotion_governance):
            source_summary = dict(dict(payload or {}).get("source_summary") or {})
            status = str(source_summary.get("family_execution_status") or "").lower()
            if status in {"healthy", "watch", "manual_review"}:
                return status
        return "unavailable"

    def _mode_state(
        self,
        *,
        mode_advisory: dict[str, Any],
        family: str,
        promotion_governance: dict[str, Any],
    ) -> str:
        rows = {
            str(row.get("bucket") or "unknown").strip().lower(): dict(row)
            for row in self._rows(mode_advisory, "family")
        }
        row = dict(rows.get(family) or {})
        advisory_state = str(row.get("advisory_state") or "").lower()
        if advisory_state:
            return advisory_state

        source_summary = dict(promotion_governance.get("source_summary") or {})
        advisory_state = str(source_summary.get("family_mode_advisory_state") or "").lower()
        return advisory_state or "unavailable"

    @staticmethod
    def _approval_penalty_status(outcome_control_trace: dict[str, Any]) -> str:
        status = str(outcome_control_trace.get("approval_penalty_status") or "").lower()
        if status:
            return status
        approval = dict(outcome_control_trace.get("approval_penalty") or {})
        return str(approval.get("status") or "healthy").lower()

    @staticmethod
    def _has_thin_sample(*payloads: dict[str, Any]) -> bool:
        for payload in payloads:
            reason_codes = list(dict(payload or {}).get("reason_codes") or [])
            if "sample:thin_sample" in reason_codes:
                return True
            if str(dict(payload or {}).get("maturity") or "").lower() == "thin_sample":
                return True
            source_summary = dict(dict(payload or {}).get("source_summary") or {})
            if str(source_summary.get("rollout_maturity") or "").lower() == "thin_sample":
                return True
        return False

    def generate(
        self,
        *,
        promotion_governance: dict[str, Any] | None,
        promotion_review_queue: dict[str, Any] | None,
        promotion_remediation_queue: dict[str, Any] | None,
        promotion_clearance_tracker: dict[str, Any] | None,
        promotion_reopen_queue: dict[str, Any] | None,
        promotion_decision_brief: dict[str, Any] | None,
        rollout_recommendation: dict[str, Any] | None,
        strategy_lifecycle: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        mode_advisory: dict[str, Any] | None,
        outcome_control_trace: dict[str, Any] | None,
        positive_evidence_expansion: dict[str, Any] | None,
    ) -> dict[str, Any]:
        governance_payload = self._dict(promotion_governance)
        review_payload = self._dict(promotion_review_queue)
        remediation_payload = self._dict(promotion_remediation_queue)
        clearance_payload = self._dict(promotion_clearance_tracker)
        reopen_payload = self._dict(promotion_reopen_queue)
        decision_payload = self._dict(promotion_decision_brief)
        rollout_payload = self._dict(rollout_recommendation)
        lifecycle_payload = self._dict(strategy_lifecycle)
        family_execution_payload = self._dict(family_execution_degradation_advisory)
        mode_payload = self._dict(mode_advisory)
        outcome_control_payload = self._dict(outcome_control_trace)
        positive_payload = self._dict(positive_evidence_expansion)

        if not any(
            [
                governance_payload,
                review_payload,
                remediation_payload,
                clearance_payload,
                reopen_payload,
                decision_payload,
                rollout_payload,
                lifecycle_payload,
                family_execution_payload,
                mode_payload,
                outcome_control_payload,
                positive_payload,
            ]
        ):
            return {
                "available": False,
                "advisory_only": True,
                "summary": "auto promotion rollout execution unavailable",
            }

        family = self._select_family(
            promotion_decision_brief=decision_payload,
            promotion_reopen_queue=reopen_payload,
            promotion_clearance_tracker=clearance_payload,
            promotion_remediation_queue=remediation_payload,
            promotion_governance=governance_payload,
            rollout_recommendation=rollout_payload,
        )
        if not family:
            return {
                "available": False,
                "advisory_only": True,
                "summary": "auto promotion rollout execution unavailable",
            }

        review_row = self._review_row(promotion_review_queue=review_payload, family=family)
        remediation_row = self._remediation_row(promotion_remediation_queue=remediation_payload, family=family)
        reopen_row = self._reopen_row(promotion_reopen_queue=reopen_payload, family=family)

        brief_state = (
            str(decision_payload.get("brief_state") or "observe_case").lower()
            if str(decision_payload.get("family") or "").strip().lower() == family
            else "observe_case"
        )
        decision_target_posture = (
            str(decision_payload.get("target_posture") or "keep_current").lower()
            if str(decision_payload.get("family") or "").strip().lower() == family
            else "keep_current"
        )
        governance_target_posture = (
            str(governance_payload.get("target_posture") or "keep_current").lower()
            if str(governance_payload.get("family") or "").strip().lower() == family
            else "keep_current"
        )
        promotion_state = (
            str(governance_payload.get("state") or "hold").lower()
            if str(governance_payload.get("family") or "").strip().lower() == family
            else str(review_row.get("promotion_state") or "hold").lower()
        )
        governance_confidence = (
            self._normalize_confidence(governance_payload.get("confidence"))
            if str(governance_payload.get("family") or "").strip().lower() == family
            else self._normalize_confidence(review_row.get("confidence"))
        )
        clearance_state = (
            str(clearance_payload.get("clearance_state") or "observe_only").lower()
            if str(clearance_payload.get("family") or "").strip().lower() == family
            else str(reopen_row.get("clearance_state") or "observe_only").lower()
        )
        clearance_confidence = (
            self._normalize_confidence(clearance_payload.get("confidence"))
            if str(clearance_payload.get("family") or "").strip().lower() == family
            else self._normalize_confidence(reopen_row.get("confidence"))
        )
        reopen_action = str(
            reopen_row.get("reopen_action")
            or (
                reopen_payload.get("top_reopen_action")
                if str(reopen_payload.get("headline_family") or "").strip().lower() == family
                else ""
            )
            or ""
        ).lower()
        remediation_action = str(
            remediation_row.get("remediation_action")
            or (
                remediation_payload.get("top_remediation_action")
                if str(remediation_payload.get("headline_family") or "").strip().lower() == family
                else ""
            )
            or ""
        ).lower()
        rollout_family = str(rollout_payload.get("family") or "").strip().lower()
        rollout_action = (
            str(rollout_payload.get("recommendation") or "").lower()
            if not rollout_family or rollout_family == family
            else ""
        )
        lifecycle_state = (
            str(lifecycle_payload.get("state") or "unknown").lower()
            if str(lifecycle_payload.get("family") or "").strip().lower() == family
            else str(dict(governance_payload.get("source_summary") or {}).get("lifecycle_state") or "unknown").lower()
        )
        positive_state = (
            str(positive_payload.get("state") or "").lower()
            if str(positive_payload.get("family") or "").strip().lower() == family
            else ""
        )
        positive_bias = (
            str(positive_payload.get("expansion_bias") or "").lower()
            if str(positive_payload.get("family") or "").strip().lower() == family
            else ""
        )
        positive_confidence = self._normalize_confidence(
            positive_payload.get("confidence")
            if str(positive_payload.get("family") or "").strip().lower() == family
            else None
        )
        family_execution_status = self._family_execution_status(
            family_execution_degradation_advisory=family_execution_payload,
            family=family,
            promotion_governance=governance_payload,
            promotion_decision_brief=decision_payload,
            promotion_clearance_tracker=clearance_payload,
        )
        mode_state = self._mode_state(
            mode_advisory=mode_payload,
            family=family,
            promotion_governance=governance_payload,
        )
        approval_penalty_status = self._approval_penalty_status(outcome_control_payload)
        thin_sample = self._has_thin_sample(
            decision_payload,
            reopen_payload,
            clearance_payload,
            governance_payload,
            rollout_payload,
            lifecycle_payload,
            positive_payload,
        )

        target_posture = decision_target_posture
        if target_posture not in {"probation", "production", "keep_current"}:
            target_posture = governance_target_posture
        if target_posture not in {"probation", "production", "keep_current"}:
            target_posture = "keep_current"

        dry_run_ready = all(
            [
                brief_state == "reopen_candidate",
                reopen_action == "reopen_review",
                clearance_state == "clearance_ready",
                promotion_state == "promotable",
                rollout_action in {"expand", "hold"},
                lifecycle_state in {"probation", "production"},
                family_execution_status in {"healthy", "unavailable"},
                approval_penalty_status not in {"manual_review", "blocked"},
            ]
        )
        semi_auto_ready = all(
            [
                dry_run_ready,
                positive_state == "expandable",
                positive_bias == "consider_expand",
                rollout_action == "expand",
                governance_target_posture in {"probation", "production"},
                target_posture in {"probation", "production"},
            ]
        )

        blocked = any(
            [
                brief_state == "observe_case",
                reopen_action != "reopen_review",
                clearance_state in {"blocked", "observe_only"},
                remediation_action in _ACTIVE_REMEDIATION_ACTIONS,
                family_execution_status in {"watch", "manual_review"},
                mode_state in {"research_only", "restrict", "stop"},
                approval_penalty_status in {"manual_review", "blocked"},
                thin_sample,
            ]
        )

        if blocked:
            execution_stage = "auto_execution_blocked"
            execution_bias = "block_auto_execution"
            action_domain = "no_write_observe"
            write_scope = "none"
            dry_run_only = False
            confidence = "low"
        elif semi_auto_ready:
            execution_stage = "semi_auto_candidate"
            execution_bias = "consider_semi_auto"
            action_domain = "rollout_policy_delta" if rollout_action == "expand" else "promotion_posture_update"
            write_scope = "proposal_only"
            dry_run_only = False
            confidence = (
                "high"
                if clearance_confidence == "high"
                and governance_confidence in {"medium", "high"}
                and positive_confidence in {"medium", "high"}
                and family_execution_status == "healthy"
                else "medium"
            )
        elif dry_run_ready:
            execution_stage = "dry_run_execution"
            execution_bias = "prepare_dry_run"
            if rollout_action == "expand":
                action_domain = "rollout_policy_delta"
            elif target_posture in {"probation", "production"}:
                action_domain = "promotion_posture_update"
            else:
                action_domain = "no_write_observe"
            write_scope = "none"
            dry_run_only = True
            confidence = (
                "high"
                if clearance_confidence == "high"
                and governance_confidence in {"medium", "high"}
                and rollout_action == "expand"
                and family_execution_status in {"healthy", "unavailable"}
                else "medium"
            )
        else:
            execution_stage = "advisory_only"
            execution_bias = "keep_manual"
            action_domain = "no_write_observe"
            write_scope = "none"
            dry_run_only = False
            confidence = "low"

        if execution_stage == "auto_execution_blocked":
            summary = (
                f"family={family} auto execution remains blocked; keep governance changes advisory-only until guardrails clear."
            )
        elif execution_stage == "semi_auto_candidate":
            summary = (
                f"family={family} is eligible for operator-confirmable semi-auto proposal execution; keep write scope proposal-only."
            )
        elif execution_stage == "dry_run_execution":
            summary = (
                f"family={family} is eligible for audit-only dry-run execution review; generate proposal artifacts but do not write policy rows."
            )
        else:
            summary = f"family={family} remains manual-only; keep promotion and rollout review compare-only."

        reason_codes = [
            f"auto_execution:{execution_stage}",
            f"promotion_decision_brief:{brief_state}",
            f"promotion_reopen_queue:{reopen_action or 'none'}",
            f"promotion_clearance:{clearance_state}",
            f"promotion_governance:{promotion_state}",
            f"rollout_recommendation:{rollout_action or 'none'}",
            f"lifecycle:{lifecycle_state or 'unknown'}",
        ]
        if remediation_action:
            reason_codes.append(f"remediation_queue:{remediation_action}")
        if family_execution_status in {"healthy", "watch", "manual_review"}:
            reason_codes.append(f"execution_guardrail:{family_execution_status}")
        if mode_state and mode_state != "unavailable":
            reason_codes.append(f"mode_guardrail:{mode_state}")
        if approval_penalty_status:
            reason_codes.append(f"approval_penalty:{approval_penalty_status}")
        if positive_state:
            reason_codes.append(f"positive_expansion:{positive_state}")
        if thin_sample:
            reason_codes.append("sample:thin_sample")

        return {
            "available": True,
            "advisory_only": True,
            "execution_stage": execution_stage,
            "execution_bias": execution_bias,
            "action_domain": action_domain,
            "target_family": family,
            "target_posture": target_posture,
            "write_scope": write_scope,
            "dry_run_only": dry_run_only,
            "confidence": confidence,
            "summary": summary,
            "reason_codes": self._dedupe(reason_codes),
            "source_summary": {
                "promotion_state": promotion_state,
                "brief_state": brief_state,
                "reopen_action": reopen_action or "none",
                "clearance_state": clearance_state,
                "remediation_action": remediation_action or "none",
                "rollout_recommendation": rollout_action or "none",
                "lifecycle_state": lifecycle_state,
                "family_execution_status": family_execution_status,
                "mode_state": mode_state,
                "approval_penalty_status": approval_penalty_status,
                "positive_expansion_state": positive_state or "none",
                "governance_target_posture": governance_target_posture,
            },
        }
