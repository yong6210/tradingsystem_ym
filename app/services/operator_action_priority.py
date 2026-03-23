from __future__ import annotations

from typing import Any


class OperatorActionPriorityService:
    _PRIORITY_RANK = {
        "urgent": 3,
        "watch": 2,
        "research": 1,
        "monitor": 0,
    }
    _SOURCE_RANK = {
        "playbook": 6,
        "execution_degradation": 5,
        "family_execution_degradation": 4,
        "opportunity_capture": 3,
        "mode_advisory": 2,
        "alpha_research": 1,
        "monitor": 0,
    }

    @classmethod
    def _priority_rank(cls, value: str) -> int:
        return int(cls._PRIORITY_RANK.get(str(value or "monitor"), 0))

    @classmethod
    def _source_rank(cls, value: str) -> int:
        return int(cls._SOURCE_RANK.get(str(value or "monitor"), 0))

    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _push_action(
        actions: list[dict[str, Any]],
        *,
        action: str | None,
        reason: str | None,
        priority_level: str,
        source: str,
        action_family: str | None = None,
    ) -> None:
        if not action:
            return
        actions.append(
            {
                "action": str(action),
                "reason": str(reason or ""),
                "priority_level": str(priority_level or "monitor"),
                "source": source,
                "action_family": str(action_family or "monitor"),
                "advisory_only": True,
            }
        )

    @staticmethod
    def _normalize_priority_source(value: str | None) -> str:
        source = str(value or "").strip().lower()
        if source.startswith("alpha_research"):
            return "alpha_research"
        if source in {
            "playbook",
            "execution_degradation",
            "family_execution_degradation",
            "opportunity_capture",
            "mode_advisory",
            "alpha_research",
        }:
            return source
        return "monitor"

    @staticmethod
    def _capture_reason_template(*, stage: str, reason: str) -> tuple[str, str, str]:
        if reason == "thin_activity_window":
            return (
                "observe_activity_window_before_threshold_changes",
                "activity is too thin to separate scarcity from degradation",
                "observe",
            )
        if stage == "runtime_to_submit" and reason == "quality_blocking":
            return (
                "review_selection_bottleneck_before_threshold_changes",
                "runtime-to-submit throughput is constrained by quality blocking",
                "selection_review",
            )
        if stage == "runtime_to_submit" and reason == "rollout_blocking":
            return (
                "review_rollout_constraints_before_threshold_changes",
                "runtime-to-submit throughput is constrained by rollout blocking",
                "rollout_review",
            )
        if stage == "runtime_to_submit" and reason == "structural_blocking":
            return (
                "review_structural_capacity_before_threshold_changes",
                "runtime-to-submit throughput is constrained by structural capacity limits",
                "capacity_review",
            )
        if stage == "runtime_to_submit":
            return (
                "review_candidate_supply_before_threshold_changes",
                "runtime-to-submit throughput remains low despite limited explicit blocking",
                "selection_review",
            )
        if stage == "submit_to_fill" and reason == "execution_fill_shortfall":
            return (
                "review_execution_fill_shortage_before_strategy_changes",
                "submission-to-fill throughput is degrading at the fill stage",
                "execution_review",
            )
        if stage == "submit_to_fill":
            return (
                "review_submission_to_fill_dropoff_before_strategy_changes",
                "submission-to-fill throughput drops before orders convert into fills",
                "execution_review",
            )
        if stage == "fill_to_close" and reason == "fill_to_close_dropoff":
            return (
                "review_position_resolution_delay_before_strategy_changes",
                "fills are occurring, but close throughput lags after entry",
                "execution_review",
            )
        return (
            "review_position_resolution_delay_before_strategy_changes",
            "position resolution remains slow after fills",
            "execution_review",
        )

    @staticmethod
    def _capture_priority(*, reason: str, action_family: str) -> str:
        if reason == "thin_activity_window":
            return "monitor"
        if action_family in {"selection_review", "rollout_review"} and reason in {
            "quality_blocking",
            "rollout_blocking",
        }:
            return "watch"
        if action_family == "execution_review" and reason == "execution_fill_shortfall":
            return "watch"
        return "monitor"

    def _capture_context(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        summary = self._dict(payload)
        if not summary or not bool(summary.get("available", False)):
            return None
        return {
            "available": True,
            "dominant_bottleneck": self._dict(summary.get("dominant_bottleneck")),
            "family_focus": self._dict(summary.get("family_focus")),
            "maturity": str(summary.get("maturity") or "unknown"),
            "regime_modifier": self._dict(summary.get("regime_modifier")),
            "session_modifier": self._dict(summary.get("session_modifier")),
        }

    def _capture_action_candidate(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        context = self._capture_context(payload)
        if not context:
            return None
        dominant_bottleneck = self._dict(context.get("dominant_bottleneck"))
        family_focus = self._dict(context.get("family_focus"))
        regime_modifier = self._dict(context.get("regime_modifier"))
        session_modifier = self._dict(context.get("session_modifier"))
        stage = str(dominant_bottleneck.get("stage") or "")
        reason = str(dominant_bottleneck.get("reason") or "")
        maturity = str(context.get("maturity") or "unknown")
        if maturity == "thin_activity":
            reason = "thin_activity_window"
        action, reason_text, action_family = self._capture_reason_template(stage=stage, reason=reason)
        priority_level = self._capture_priority(reason=reason, action_family=action_family)
        family_key = str(family_focus.get("key") or "unknown")
        if family_key and family_key != "unknown":
            reason_text = f"{reason_text}; family focus is {family_key}"
        if str(regime_modifier.get("state") or "") == "negative":
            reason_text = f"{reason_text}; regime modifier is negative"
        if str(session_modifier.get("state") or "") == "negative":
            reason_text = f"{reason_text}; session modifier is negative"
        return {
            "action": action,
            "reason": reason_text,
            "priority_level": priority_level,
            "source": "opportunity_capture",
            "action_family": action_family,
            "advisory_only": True,
        }

    def generate(
        self,
        *,
        dashboard: dict[str, Any] | None,
        checklist: dict[str, Any] | None,
        validation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        dashboard_payload = self._dict(dashboard)
        checklist_payload = self._dict(checklist)
        validation_payload = self._dict(validation)

        funnel = self._dict(dashboard_payload.get("signal_funnel"))
        degradation = self._dict(funnel.get("execution_degradation_advisory"))
        family_execution = self._dict(funnel.get("family_execution_degradation_advisory"))
        mode_advisory = self._dict(funnel.get("mode_advisory"))
        research_action = self._dict(funnel.get("alpha_research_recommended_action"))
        softening_review = self._dict(funnel.get("alpha_research_softening_review"))
        promotion_watchlist = self._dict(funnel.get("alpha_research_promotion_watchlist"))
        opportunity_capture = self._dict(
            funnel.get("opportunity_capture") or validation_payload.get("opportunity_capture_summary")
        )

        playbook_action = (
            dashboard_payload.get("playbook_action")
            or checklist_payload.get("playbook_action")
            or validation_payload.get("playbook_action")
            or ""
        )
        playbook_reason = (
            dashboard_payload.get("playbook_message")
            or checklist_payload.get("playbook_message")
            or validation_payload.get("playbook_message")
            or validation_payload.get("deployment_message")
            or ""
        )

        top_family_execution = self._dict(family_execution.get("top_family"))
        mode_family_top = self._dict(mode_advisory.get("family_top"))
        mode_regime_top = self._dict(mode_advisory.get("regime_top"))
        mode_session_top = self._dict(mode_advisory.get("session_top"))
        mode_top = next(
            (
                row
                for row in [mode_family_top, mode_regime_top, mode_session_top]
                if row.get("bucket")
            ),
            {},
        )

        next_actions: list[dict[str, Any]] = []

        if playbook_action:
            self._push_action(
                next_actions,
                action=str(playbook_action),
                reason=str(playbook_reason),
                priority_level="urgent",
                source="playbook",
                action_family="playbook",
            )

        degradation_status = str(degradation.get("status") or "")
        if degradation_status == "manual_review":
            self._push_action(
                next_actions,
                action=(
                    degradation.get("recommended_action")
                    or "review_execution_drag_before_expansion"
                ),
                reason=(
                    degradation.get("summary")
                    or "global execution degradation requires manual review"
                ),
                priority_level="urgent",
                source="execution_degradation",
                action_family="execution_review",
            )
        elif degradation_status == "watch":
            self._push_action(
                next_actions,
                action=(
                    degradation.get("recommended_action")
                    or "review_execution_drag_and_hold_size"
                ),
                reason=(
                    degradation.get("summary")
                    or "global execution quality is drifting"
                ),
                priority_level="watch",
                source="execution_degradation",
                action_family="execution_review",
            )

        if top_family_execution.get("family"):
            family_status = str(top_family_execution.get("status") or "")
            family_action = top_family_execution.get("recommended_action") or (
                f"review_family_{top_family_execution.get('family')}_execution_drag"
            )
            family_reason = top_family_execution.get("summary") or (
                f"family={top_family_execution.get('family')} status={family_status or 'n/a'}"
            )
            family_priority = "monitor"
            if family_status in {"manual_review", "watch"}:
                family_priority = "watch"
            self._push_action(
                next_actions,
                action=str(family_action),
                reason=str(family_reason),
                priority_level=family_priority,
                source="family_execution_degradation",
                action_family="execution_review",
            )

        capture_candidate = self._capture_action_candidate(opportunity_capture)
        if capture_candidate:
            next_actions.append(capture_candidate)

        advisory_state = str(mode_top.get("advisory_state") or "")
        if advisory_state == "research_only":
            self._push_action(
                next_actions,
                action="keep_bucket_in_research_only_review",
                reason=(
                    mode_top.get("why")
                    or f"{mode_top.get('axis') or 'bucket'}={mode_top.get('bucket') or 'unknown'} remains research-only"
                ),
                priority_level="research",
                source="mode_advisory",
                action_family="mode_review",
            )
        elif advisory_state == "promotion_watch":
            self._push_action(
                next_actions,
                action="keep_bucket_under_promotion_watch",
                reason=(
                    mode_top.get("why")
                    or f"{mode_top.get('axis') or 'bucket'}={mode_top.get('bucket') or 'unknown'} stays on promotion watch"
                ),
                priority_level="watch",
                source="mode_advisory",
                action_family="mode_review",
            )
        elif advisory_state == "watch":
            self._push_action(
                next_actions,
                action="watch_bucket_execution_and_outcome",
                reason=(
                    mode_top.get("why")
                    or f"{mode_top.get('axis') or 'bucket'}={mode_top.get('bucket') or 'unknown'} should be watched"
                ),
                priority_level="watch",
                source="mode_advisory",
                action_family="mode_review",
            )

        if research_action.get("recommended_action"):
            self._push_action(
                next_actions,
                action=str(research_action.get("recommended_action") or ""),
                reason=str(research_action.get("recommended_reason") or "alpha-research next step"),
                priority_level="research",
                source="alpha_research",
                action_family="research",
            )
        else:
            top_candidate = self._dict(softening_review.get("top_candidate"))
            top_watch = self._dict(promotion_watchlist.get("top_watch"))
            if top_candidate.get("bucket"):
                self._push_action(
                    next_actions,
                    action="softening_review",
                    reason=f"{top_candidate.get('axis') or 'bucket'}={top_candidate.get('bucket')}",
                    priority_level="research",
                    source="alpha_research_softening",
                    action_family="research",
                )
            elif top_watch.get("bucket"):
                self._push_action(
                    next_actions,
                    action="promotion_watch",
                    reason=f"{top_watch.get('focus') or 'bucket'}={top_watch.get('bucket')}",
                    priority_level="research",
                    source="alpha_research_promotion_watch",
                    action_family="research",
                )

        next_actions.sort(
            key=lambda item: (
                -self._priority_rank(str(item.get("priority_level") or "monitor")),
                -self._source_rank(self._normalize_priority_source(str(item.get("source") or ""))),
                str(item.get("action") or ""),
            )
        )

        top = self._dict(next_actions[0] if next_actions else {})
        capture_context = self._capture_context(opportunity_capture)
        if not top:
            return {
                "available": True,
                "top_action": "continue_runtime_monitoring",
                "top_reason": (
                    "no stronger operator action is currently implied by playbook, execution, family, mode, or research signals"
                ),
                "priority_level": "monitor",
                "priority_source": "monitor",
                "action_family": "monitor",
                "supporting_signals": [],
                "blocking_signals": [],
                "next_actions": [],
                "capture_context": capture_context,
                "advisory_only": True,
            }

        supporting_signals: list[str] = []
        blocking_signals: list[str] = []
        if playbook_action:
            supporting_signals.append(f"playbook:{playbook_action}")
        if degradation_status:
            supporting_signals.append(f"execution:{degradation_status}")
        if top_family_execution.get("family"):
            supporting_signals.append(
                f"family:{top_family_execution.get('family')}:{top_family_execution.get('status') or 'n/a'}"
            )
        if mode_top.get("bucket"):
            supporting_signals.append(
                f"mode:{mode_top.get('axis') or 'bucket'}={mode_top.get('bucket')}:{mode_top.get('advisory_state') or 'n/a'}"
            )
        if research_action.get("recommended_action"):
            supporting_signals.append(f"research:{research_action.get('recommended_action')}")
        if capture_context:
            dominant_bottleneck = self._dict(capture_context.get("dominant_bottleneck"))
            stage = str(dominant_bottleneck.get("stage") or "")
            reason = str(dominant_bottleneck.get("reason") or "")
            if stage or reason:
                supporting_signals.append(f"capture:{stage or 'unknown'}:{reason or 'unknown'}")
            family_key = str(self._dict(capture_context.get("family_focus")).get("key") or "")
            if family_key:
                supporting_signals.append(f"capture_family:{family_key}")
            maturity = str(capture_context.get("maturity") or "")
            if maturity:
                supporting_signals.append(f"capture_maturity:{maturity}")
            regime_state = str(self._dict(capture_context.get("regime_modifier")).get("state") or "")
            if regime_state == "negative":
                supporting_signals.append("capture_regime:negative")
            session_state = str(self._dict(capture_context.get("session_modifier")).get("state") or "")
            if session_state == "negative":
                supporting_signals.append("capture_session:negative")

        if dashboard_payload.get("new_entries_allowed") is False:
            blocking_signals.append(
                f"entry_gate:{dashboard_payload.get('blocking_reason_code') or 'blocked'}"
            )
        if str(top_family_execution.get("status") or "") == "manual_review" and top_family_execution.get("family"):
            blocking_signals.append(
                f"family_manual_review:{top_family_execution.get('family')}"
            )
        if advisory_state == "research_only":
            blocking_signals.append(
                f"research_only:{mode_top.get('axis') or 'bucket'}={mode_top.get('bucket') or 'unknown'}"
            )

        return {
            "available": True,
            "top_action": str(top.get("action") or "continue_runtime_monitoring"),
            "top_reason": str(top.get("reason") or ""),
            "priority_level": str(top.get("priority_level") or "monitor"),
            "priority_source": self._normalize_priority_source(str(top.get("source") or "")),
            "action_family": str(top.get("action_family") or "monitor"),
            "supporting_signals": supporting_signals,
            "blocking_signals": blocking_signals,
            "next_actions": next_actions[1:4],
            "capture_context": capture_context,
            "advisory_only": True,
        }
