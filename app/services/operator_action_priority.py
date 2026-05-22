from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from app.services.market_data import configured_usdt_universe_name


class OperatorActionPriorityService:
    _REVIEW_PACKET_FRESH_HOURS = 12
    _REVIEW_PACKET_NO_TARGET_COOLDOWN_HOURS = 6
    _REVIEW_PACKET_REPEAT_LIMIT = 3
    _PRIORITY_RANK: ClassVar[dict[str, int]] = {
        "urgent": 3,
        "watch": 2,
        "research": 1,
        "monitor": 0,
    }
    _SOURCE_RANK: ClassVar[dict[str, int]] = {
        "playbook": 6,
        "execution_degradation": 5,
        "family_execution_degradation": 4,
        "edge_evolution": 3,
        "opportunity_capture": 2,
        "edge_experiment": 1,
        "mode_advisory": 1,
        "alpha_research": 0,
        "monitor": 0,
    }
    _REVIEW_FOLLOWUP_ACTION_TARGETS: ClassVar[dict[str, str]] = {
        "run_entry_timing_split_review": "entry_timing_target",
        "run_execution_style_split_review": "execution_style_target",
        "promote_entry_timing_branch_review": "entry_timing_target",
        "promote_execution_style_branch_review": "execution_style_target",
        "promote_preferred_branch_review": "",
        "reduce_baseline_allocation_review": "",
        "review_edge_kill_condition": "",
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
    def _int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return bool(default)

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @classmethod
    def _age_hours(cls, value: Any) -> float | None:
        parsed = cls._parse_datetime(value)
        if parsed is None:
            return None
        return max((datetime.now(UTC) - parsed).total_seconds() / 3600.0, 0.0)

    def _command_context(
        self,
        *,
        dashboard_payload: dict[str, Any] | None,
        validation_payload: dict[str, Any] | None,
        opportunity_capture_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        dashboard = self._dict(dashboard_payload)
        validation_source = self._dict(self._dict(validation_payload).get("validation_report") or validation_payload)
        portfolio = self._dict(dashboard.get("portfolio_summary"))
        score_to_outcome = self._dict(validation_source.get("score_to_outcome_funnel_summary"))
        opportunity_capture = self._dict(opportunity_capture_payload)
        return {
            "symbol": str(dashboard.get("symbol") or validation_source.get("symbol") or ""),
            "universe": str(
                portfolio.get("universe")
                or dashboard.get("universe")
                or opportunity_capture.get("universe")
                or configured_usdt_universe_name()
            ),
            "days": max(
                self._int(
                    dashboard.get("report_window_days")
                    or score_to_outcome.get("report_window_days")
                    or opportunity_capture.get("report_window_days")
                    or 7,
                    7,
                ),
                1,
            ),
        }

    def _split_review_followup_command(
        self,
        *,
        action: str,
        symbol: str,
        universe: str,
        days: int,
    ) -> str:
        if action not in self._REVIEW_FOLLOWUP_ACTION_TARGETS or not symbol:
            return ""
        return (
            f"./.venv/bin/python scripts/run_split_review_followup.py "
            f"--symbol {symbol.upper()} --universe {universe} --days {max(int(days), 1)} --action {action}"
        )

    def _decorate_experiment_target(
        self,
        target: dict[str, Any] | None,
        *,
        action: str,
        command_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        item = self._dict(target)
        if not item:
            return None
        item["followup_command"] = self._split_review_followup_command(
            action=action,
            symbol=str(item.get("symbol") or command_context.get("symbol") or ""),
            universe=str(command_context.get("universe") or configured_usdt_universe_name()),
            days=max(self._int(command_context.get("days"), 7), 1),
        )
        return item

    def _decorate_action_followup(
        self,
        action_payload: dict[str, Any] | None,
        *,
        command_context: dict[str, Any],
    ) -> dict[str, Any]:
        item = self._dict(action_payload)
        item["followup_command"] = self._split_review_followup_command(
            action=str(item.get("action") or ""),
            symbol=str(item.get("target_symbol") or command_context.get("symbol") or ""),
            universe=str(command_context.get("universe") or configured_usdt_universe_name()),
            days=max(self._int(command_context.get("days"), 7), 1),
        )
        return item

    def _review_followup_packets(self, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        summary = self._dict(payload)
        recent_packets = [
            self._dict(item)
            for item in list(summary.get("recent_packets") or [])
            if isinstance(item, dict)
        ]
        if recent_packets:
            return recent_packets
        last_action = str(summary.get("last_action") or "none")
        if last_action in {"", "none"}:
            return []
        return [
            {
                "action": last_action,
                "status": str(summary.get("last_status") or "none"),
                "generated_at": str(summary.get("last_generated_at") or ""),
                "recorded_at": str(summary.get("last_recorded_at") or ""),
                "target_contract": self._dict(summary.get("last_target_contract")),
                "packet_key": str(summary.get("last_packet_key") or ""),
            }
        ]

    def _candidate_packet_key(self, action_payload: dict[str, Any] | None) -> str:
        item = self._dict(action_payload)
        return "|".join(
            [
                str(item.get("action") or "none"),
                str(item.get("target_axis") or "none"),
                str(item.get("target_preferred_variant") or "none"),
                str(item.get("target_symbol") or "").upper() or "none",
                str(item.get("target_family") or "none"),
            ]
        )

    def _ledger_packet_key(self, packet: dict[str, Any] | None) -> str:
        item = self._dict(packet)
        direct = str(item.get("packet_key") or "")
        if direct:
            return direct
        target = self._dict(item.get("target_contract"))
        return "|".join(
            [
                str(item.get("action") or "none"),
                str(target.get("axis") or "none"),
                str(target.get("preferred_variant") or "none"),
                str(target.get("symbol") or "").upper() or "none",
                str(target.get("strategy_family") or "none"),
            ]
        )

    def _review_action_dedupe_reason(
        self,
        action_payload: dict[str, Any] | None,
        *,
        review_followup_ledger: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        item = self._dict(action_payload)
        action = str(item.get("action") or "")
        if action not in self._REVIEW_FOLLOWUP_ACTION_TARGETS:
            return None

        packets = self._review_followup_packets(review_followup_ledger)
        if not packets:
            return None

        packet_key = self._candidate_packet_key(item)
        last_packet = self._dict(packets[0])
        last_action = str(last_packet.get("action") or "none")
        last_status = str(last_packet.get("status") or "UNKNOWN")
        if last_action == action and last_status in {"NO_TARGET", "NO_REVIEW_ACTION_AVAILABLE"}:
            age_hours = self._age_hours(last_packet.get("generated_at") or last_packet.get("recorded_at"))
            if age_hours is None or age_hours <= self._REVIEW_PACKET_NO_TARGET_COOLDOWN_HOURS:
                target_symbol = str(item.get("target_symbol") or "").upper()
                last_target = self._dict(last_packet.get("target_contract"))
                last_target_symbol = str(last_target.get("symbol") or "").upper()
                if not target_symbol or not last_target_symbol or target_symbol == last_target_symbol:
                    return {
                        "reason": "last_packet_had_no_target",
                        "message": "the most recent packet for this review action already stalled at NO_TARGET",
                        "matched_packet": last_packet,
                    }

        for packet in packets:
            packet_item = self._dict(packet)
            if str(packet_item.get("status") or "UNKNOWN") != "READY":
                continue
            if packet_key != self._ledger_packet_key(packet_item):
                continue
            age_hours = self._age_hours(packet_item.get("generated_at") or packet_item.get("recorded_at"))
            if age_hours is not None and age_hours <= self._REVIEW_PACKET_FRESH_HOURS:
                return {
                    "reason": "fresh_packet_already_exists",
                    "message": "an equivalent READY review packet already exists in the fresh ledger window",
                    "matched_packet": packet_item,
                }

        leading_packets = [self._dict(packet) for packet in packets[: self._REVIEW_PACKET_REPEAT_LIMIT]]
        if len(leading_packets) >= self._REVIEW_PACKET_REPEAT_LIMIT and all(
            str(packet.get("action") or "none") == action for packet in leading_packets
        ):
            matching_repeat_count = sum(
                1 for packet in leading_packets if self._ledger_packet_key(packet) == packet_key
            )
            if matching_repeat_count >= self._REVIEW_PACKET_REPEAT_LIMIT:
                return {
                    "reason": "same_packet_repeated_three_times",
                    "message": "the same review packet has already been generated three times in a row",
                    "matched_packet": leading_packets[0],
                }
            if not str(item.get("target_symbol") or "").strip() and matching_repeat_count <= 1:
                return {
                    "reason": "same_action_repeated_three_times",
                    "message": "the same review action has already been generated three times in a row",
                    "matched_packet": leading_packets[0],
                }

        return None

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

    @classmethod
    def _sample_context_has_material_execution(cls, payload: dict[str, Any]) -> bool:
        sample = cls._dict(payload.get("sample_context"))
        return any(
            cls._int(sample.get(key), default=0) > 0
            for key in ("plans_matured", "fill_events_total", "closed_plans")
        )

    @classmethod
    def _execution_degradation_priority(cls, payload: dict[str, Any]) -> str:
        status = str(payload.get("status") or "").strip().lower()
        material_sample = cls._sample_context_has_material_execution(payload)
        if status == "manual_review":
            return "urgent" if material_sample else "monitor"
        if status == "watch":
            return "watch" if material_sample else "monitor"
        return "monitor"

    @staticmethod
    def _playbook_priority(action: str | None, reason: str | None = None) -> str:
        normalized = str(action or "").strip().lower()
        reason_text = str(reason or "").strip().lower()
        if not normalized:
            return "monitor"
        if normalized in {
            "continue_candidate_review_under_portfolio_caps",
            "proceed_with_configured_rollout",
            "continue_runtime_monitoring",
            "wait_for_fresh_promotable_candidate",
            "wait_for_live_candidate",
        } or normalized.startswith(("continue_", "proceed_", "wait_")):
            return "monitor"
        if normalized.startswith(("clear_", "hold_", "stop_", "disable_", "lock_", "kill_")) or "no_go" in reason_text:
            return "urgent"
        if "manual_review" in reason_text or "review" in normalized:
            return "watch"
        return "monitor"

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
            "edge_experiment",
            "edge_evolution",
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

    @staticmethod
    def _is_split_experiment_action(action: str) -> bool:
        return str(action or "") in {
            "run_entry_timing_split_review",
            "run_execution_style_split_review",
        }

    @classmethod
    def _enforce_single_experiment_policy(
        cls,
        actions: list[dict[str, Any]],
        *,
        experiment_context: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        context = cls._dict(experiment_context)
        kept: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        active_experiment: dict[str, Any] = {}
        reason = "keep one split experiment active until fresh closes advance the next sample target"

        for row in actions:
            item = cls._dict(row)
            if not cls._is_split_experiment_action(str(item.get("action") or "")):
                kept.append(item)
                continue
            if not active_experiment:
                active_experiment = item
                kept.append(item)
                continue
            deferred_item = dict(item)
            deferred_item["defer_reason"] = "single_active_experiment"
            deferred_item["defer_message"] = reason
            deferred.append(deferred_item)

        return kept, deferred, {
            "mode": "single_active_experiment",
            "reason": reason,
            "active_action": str(active_experiment.get("action") or "none"),
            "active_axis": str(active_experiment.get("target_axis") or "none"),
            "sample_maturity_state": str(context.get("sample_maturity_state") or "unknown"),
            "next_sample_target_closed_trades": cls._int(
                context.get("next_sample_target_closed_trades"),
                0,
            ),
            "remaining_closed_trades_to_next_target": cls._int(
                context.get("remaining_closed_trades_to_next_target"),
                0,
            ),
            "deferred_actions": [dict(item) for item in deferred[:3]],
        }

    def _capture_context(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        summary = self._dict(payload)
        if not summary or not self._safe_bool(summary.get("available", False)):
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

    def _candidate_edge_focus(
        self,
        row: dict[str, Any] | None,
        *,
        status: str,
        focus_source: str,
    ) -> dict[str, Any] | None:
        item = self._dict(row)
        focus = self._dict(item.get("edge_experiment_focus"))
        if not item or not focus:
            return None
        return {
            "symbol": str(item.get("symbol") or ""),
            "status": status,
            "strategy_family": str(item.get("strategy_family") or "unknown"),
            "block_reason": str(item.get("block_reason") or ""),
            "edge_state": str(focus.get("edge_state") or "insufficient_edge_measurement"),
            "entry_timing_preferred_variant": str(focus.get("entry_timing_preferred_variant") or "none"),
            "execution_style_preferred_variant": str(focus.get("execution_style_preferred_variant") or "none"),
            "focus_source": focus_source,
        }

    def _edge_experiment_candidate_context(self, dashboard_payload: dict[str, Any] | None) -> dict[str, Any]:
        dashboard = self._dict(dashboard_payload)
        portfolio = self._dict(dashboard.get("portfolio_summary"))
        accepted_rows = [self._dict(item) for item in list(portfolio.get("accepted_candidates") or [])]
        blocked_rows = [self._dict(item) for item in list(portfolio.get("blocked_candidates") or [])]

        accepted_focus = next(
            (
                candidate
                for candidate in (
                    self._candidate_edge_focus(
                        row,
                        status="ACTIONABLE_ENTRY",
                        focus_source="accepted_candidate_focus",
                    )
                    for row in accepted_rows
                )
                if candidate
            ),
            None,
        )
        blocked_focus = next(
            (
                candidate
                for candidate in (
                    self._candidate_edge_focus(
                        row,
                        status="BLOCKED_SETUP",
                        focus_source="blocked_candidate_focus",
                    )
                    for row in blocked_rows
                )
                if candidate
            ),
            None,
        )
        return {
            "accepted_candidate_focus": accepted_focus,
            "blocked_candidate_focus": blocked_focus,
        }

    def _preferred_experiment_target(
        self,
        *,
        preferred_variant: str,
        variant_key: str,
        accepted_focus: dict[str, Any] | None,
        blocked_focus: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        candidates = [self._dict(accepted_focus), self._dict(blocked_focus)]
        normalized_preferred = str(preferred_variant or "none")
        if normalized_preferred and normalized_preferred != "none":
            for candidate in candidates:
                if str(candidate.get(variant_key) or "none") == normalized_preferred:
                    return candidate
        for candidate in candidates:
            if candidate:
                return candidate
        return None

    def _edge_evolution_target(
        self,
        *,
        action: str,
        experiment_context: dict[str, Any] | None,
        promotion_candidate: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        experiment = self._dict(experiment_context)
        promotion = self._dict(promotion_candidate)

        axis = ""
        if action == "promote_entry_timing_branch_review":
            axis = "entry_timing"
        elif action == "promote_execution_style_branch_review":
            axis = "execution_style"
        elif str(promotion.get("axis") or "") in {"entry_timing", "execution_style"}:
            axis = str(promotion.get("axis") or "")
        elif self._dict(experiment.get("entry_timing_target")).get("symbol"):
            axis = "entry_timing"
        elif self._dict(experiment.get("execution_style_target")).get("symbol"):
            axis = "execution_style"

        target: dict[str, Any] = {}
        preferred_variant = str(promotion.get("preferred_variant") or "none")
        if axis == "entry_timing":
            target = self._dict(experiment.get("entry_timing_target"))
            preferred_variant = str(
                promotion.get("preferred_variant")
                or experiment.get("entry_timing_preferred_variant")
                or "none"
            )
        elif axis == "execution_style":
            target = self._dict(experiment.get("execution_style_target"))
            preferred_variant = str(
                promotion.get("preferred_variant")
                or experiment.get("execution_style_preferred_variant")
                or "none"
            )

        if not target:
            target = self._dict(experiment.get("accepted_candidate_focus")) or self._dict(
                experiment.get("blocked_candidate_focus")
            )

        if not target:
            return None

        return {
            "action": action,
            "axis": axis or str(promotion.get("axis") or "branch"),
            "preferred_variant": preferred_variant,
            "symbol": str(target.get("symbol") or ""),
            "status": str(target.get("status") or ""),
            "strategy_family": str(target.get("strategy_family") or ""),
            "block_reason": str(target.get("block_reason") or ""),
            "focus_source": str(target.get("focus_source") or ""),
        }

    def _edge_experiment_context(
        self,
        payload: dict[str, Any] | None,
        *,
        dashboard_payload: dict[str, Any] | None = None,
        command_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        summary = self._dict(payload)
        if not summary or not self._safe_bool(summary.get("available", False)):
            return None
        command_context_payload = self._dict(command_context)
        context = {
            "available": True,
            "edge_state": str(summary.get("edge_state") or "insufficient_edge_measurement"),
            "true_edge_ratio": float(summary.get("true_edge_ratio", 0.0) or 0.0),
            "edge_decay_rate": float(summary.get("edge_decay_rate", 0.0) or 0.0),
            "closed_trade_count": self._int(summary.get("closed_trade_count", 0), 0),
            "sample_maturity_state": str(summary.get("sample_maturity_state") or "unknown"),
            "next_sample_target_closed_trades": self._int(summary.get("next_sample_target_closed_trades", 0), 0),
            "remaining_closed_trades_to_next_target": self._int(
                summary.get("remaining_closed_trades_to_next_target", 0),
                0,
            ),
            "regime_dependency_state": str(summary.get("regime_dependency_state") or "not_available"),
            "strongest_regime": str(summary.get("strongest_regime") or "none"),
            "weakest_regime": str(summary.get("weakest_regime") or "none"),
            "entry_timing_preferred_variant": str(summary.get("entry_timing_preferred_variant") or "none"),
            "entry_timing_recommendation_reason": str(
                summary.get("entry_timing_recommendation_reason") or "not_available"
            ),
            "entry_timing_comparison_ready": self._safe_bool(summary.get("entry_timing_comparison_ready", False)),
            "execution_style_preferred_variant": str(summary.get("execution_style_preferred_variant") or "none"),
            "execution_style_recommendation_reason": str(
                summary.get("execution_style_recommendation_reason") or "not_available"
            ),
            "execution_style_comparison_ready": self._safe_bool(summary.get("execution_style_comparison_ready", False)),
        }
        candidate_context = self._edge_experiment_candidate_context(dashboard_payload)
        accepted_focus = self._dict(candidate_context.get("accepted_candidate_focus"))
        blocked_focus = self._dict(candidate_context.get("blocked_candidate_focus"))
        context["accepted_candidate_focus"] = accepted_focus or None
        context["blocked_candidate_focus"] = blocked_focus or None
        context["entry_timing_target"] = self._decorate_experiment_target(
            self._preferred_experiment_target(
                preferred_variant=str(context.get("entry_timing_preferred_variant") or "none"),
                variant_key="entry_timing_preferred_variant",
                accepted_focus=accepted_focus,
                blocked_focus=blocked_focus,
            ),
            action="run_entry_timing_split_review",
            command_context=command_context_payload,
        )
        context["execution_style_target"] = self._decorate_experiment_target(
            self._preferred_experiment_target(
                preferred_variant=str(context.get("execution_style_preferred_variant") or "none"),
                variant_key="execution_style_preferred_variant",
                accepted_focus=accepted_focus,
                blocked_focus=blocked_focus,
            ),
            action="run_execution_style_split_review",
            command_context=command_context_payload,
        )
        return context

    def _edge_experiment_actions(
        self,
        payload: dict[str, Any] | None,
        *,
        dashboard_payload: dict[str, Any] | None = None,
        command_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        context = self._edge_experiment_context(
            payload,
            dashboard_payload=dashboard_payload,
            command_context=command_context,
        )
        if not context:
            return []

        edge_state = str(context.get("edge_state") or "insufficient_edge_measurement")
        if edge_state not in {"watch_edge", "fragile_edge"}:
            return []

        priority_level = "watch"
        actions: list[dict[str, Any]] = []
        if self._safe_bool(context.get("entry_timing_comparison_ready", False)):
            preferred = str(context.get("entry_timing_preferred_variant") or "none")
            reason = str(context.get("entry_timing_recommendation_reason") or "not_available")
            target = self._dict(context.get("entry_timing_target"))
            target_reason = ""
            if target.get("symbol"):
                target_reason = (
                    f"; target={target.get('symbol')} "
                    f"{target.get('status') or 'UNKNOWN'} "
                    f"family={target.get('strategy_family') or 'unknown'}"
                )
            actions.append(
                {
                    "action": "run_entry_timing_split_review",
                    "reason": (
                        f"edge_state={edge_state}; preferred entry timing branch is "
                        f"{preferred} ({reason}){target_reason}"
                    ),
                    "priority_level": priority_level,
                    "source": "edge_experiment",
                    "action_family": "edge_review",
                    "target_axis": "entry_timing",
                    "target_preferred_variant": preferred,
                    "target_symbol": str(target.get("symbol") or ""),
                    "target_status": str(target.get("status") or ""),
                    "target_family": str(target.get("strategy_family") or ""),
                    "target_block_reason": str(target.get("block_reason") or ""),
                    "target_focus_source": str(target.get("focus_source") or ""),
                    "advisory_only": True,
                }
            )
        if self._safe_bool(context.get("execution_style_comparison_ready", False)):
            preferred = str(context.get("execution_style_preferred_variant") or "none")
            reason = str(context.get("execution_style_recommendation_reason") or "not_available")
            target = self._dict(context.get("execution_style_target"))
            target_reason = ""
            if target.get("symbol"):
                target_reason = (
                    f"; target={target.get('symbol')} "
                    f"{target.get('status') or 'UNKNOWN'} "
                    f"family={target.get('strategy_family') or 'unknown'}"
                )
            actions.append(
                {
                    "action": "run_execution_style_split_review",
                    "reason": (
                        f"edge_state={edge_state}; preferred execution style is "
                        f"{preferred} ({reason}){target_reason}"
                    ),
                    "priority_level": priority_level,
                    "source": "edge_experiment",
                    "action_family": "edge_review",
                    "target_axis": "execution_style",
                    "target_preferred_variant": preferred,
                    "target_symbol": str(target.get("symbol") or ""),
                    "target_status": str(target.get("status") or ""),
                    "target_family": str(target.get("strategy_family") or ""),
                    "target_block_reason": str(target.get("block_reason") or ""),
                    "target_focus_source": str(target.get("focus_source") or ""),
                    "advisory_only": True,
                }
            )
        return [
            self._decorate_action_followup(item, command_context=self._dict(command_context))
            for item in actions
        ]

    def _edge_evolution_actions(
        self,
        payload: dict[str, Any] | None,
        *,
        experiment_context: dict[str, Any] | None = None,
        command_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        summary = self._dict(payload)
        if not summary or not self._safe_bool(summary.get("available", False)):
            return []

        evolution_state = str(summary.get("evolution_state") or "insufficient_sample")
        recommended_action = str(summary.get("recommended_action") or "keep_current_baseline")
        confidence = str(summary.get("confidence") or "low")
        experiment = self._dict(experiment_context)
        promotion_candidate = self._dict(summary.get("promotion_candidate"))
        command_context_payload = self._dict(command_context)

        if evolution_state == "reduce_candidate":
            target = self._dict(
                self._edge_evolution_target(
                    action="reduce_baseline_allocation_review",
                    experiment_context=experiment,
                    promotion_candidate=promotion_candidate,
                )
            )
            return [
                self._decorate_action_followup(
                    {
                        "action": "reduce_baseline_allocation_review",
                        "reason": str(
                            summary.get("summary") or "baseline allocation should be reduced while edge remains weak"
                        ),
                        "priority_level": "watch",
                        "source": "edge_evolution",
                        "action_family": "allocation_review",
                        "target_axis": str(target.get("axis") or promotion_candidate.get("axis") or "none"),
                        "target_preferred_variant": str(
                            target.get("preferred_variant") or promotion_candidate.get("preferred_variant") or "none"
                        ),
                        "target_symbol": str(target.get("symbol") or ""),
                        "target_status": str(target.get("status") or ""),
                        "target_family": str(target.get("strategy_family") or ""),
                        "target_block_reason": str(target.get("block_reason") or ""),
                        "target_focus_source": str(target.get("focus_source") or ""),
                        "advisory_only": True,
                    },
                    command_context=command_context_payload,
                )
            ]

        if evolution_state == "edge_kill_review":
            kill_state = str(self._dict(summary.get("source_summary")).get("kill_condition_state") or "observe_only")
            target = self._dict(
                self._edge_evolution_target(
                    action="review_edge_kill_condition",
                    experiment_context=experiment,
                    promotion_candidate=promotion_candidate,
                )
            )
            return [
                self._decorate_action_followup(
                    {
                        "action": "review_edge_kill_condition",
                        "reason": str(summary.get("summary") or "edge deterioration justifies kill-condition review"),
                        "priority_level": "urgent" if kill_state == "kill_switch_review" else "watch",
                        "source": "edge_evolution",
                        "action_family": "risk_review",
                        "target_axis": str(target.get("axis") or promotion_candidate.get("axis") or "none"),
                        "target_preferred_variant": str(
                            target.get("preferred_variant") or promotion_candidate.get("preferred_variant") or "none"
                        ),
                        "target_symbol": str(target.get("symbol") or ""),
                        "target_status": str(target.get("status") or ""),
                        "target_family": str(target.get("strategy_family") or ""),
                        "target_block_reason": str(target.get("block_reason") or ""),
                        "target_focus_source": str(target.get("focus_source") or ""),
                        "advisory_only": True,
                    },
                    command_context=command_context_payload,
                )
            ]

        if evolution_state != "promote_candidate":
            return []

        axis = str(promotion_candidate.get("axis") or "")
        target = self._dict(
            self._edge_evolution_target(
                action=recommended_action,
                experiment_context=experiment,
                promotion_candidate=promotion_candidate,
            )
        )

        target_reason = ""
        if target.get("symbol"):
            target_reason = (
                f"; target={target.get('symbol')} "
                f"{target.get('status') or 'UNKNOWN'} "
                f"family={target.get('strategy_family') or 'unknown'}"
            )
        action = recommended_action or (
            f"promote_{axis}_branch_review" if axis in {"entry_timing", "execution_style"} else "promote_preferred_branch_review"
        )
        return [
            self._decorate_action_followup(
                {
                    "action": action,
                    "reason": f"{summary.get('summary') or 'preferred branch promotion review is justified'}{target_reason}",
                    "priority_level": "watch" if confidence in {"medium", "high"} else "research",
                    "source": "edge_evolution",
                    "action_family": "promotion_review",
                    "target_axis": str(target.get("axis") or axis or "none"),
                    "target_preferred_variant": str(
                        target.get("preferred_variant") or promotion_candidate.get("preferred_variant") or "none"
                    ),
                    "target_symbol": str(target.get("symbol") or ""),
                    "target_status": str(target.get("status") or ""),
                    "target_family": str(target.get("strategy_family") or ""),
                    "target_focus_source": str(target.get("focus_source") or ""),
                    "advisory_only": True,
                },
                command_context=command_context_payload,
            )
        ]

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
        edge_experiment = self._dict(
            funnel.get("edge_experiment_review") or validation_payload.get("edge_experiment_review_summary")
        )
        edge_evolution = self._dict(
            funnel.get("edge_evolution_rule") or validation_payload.get("edge_evolution_rule_summary")
        )
        review_followup_ledger = self._dict(
            funnel.get("review_followup_ledger") or validation_payload.get("review_followup_ledger_summary")
        )
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

        command_context = self._command_context(
            dashboard_payload=dashboard_payload,
            validation_payload=validation_payload,
            opportunity_capture_payload=opportunity_capture,
        )
        next_actions: list[dict[str, Any]] = []

        if playbook_action:
            self._push_action(
                next_actions,
                action=str(playbook_action),
                reason=str(playbook_reason),
                priority_level=self._playbook_priority(playbook_action, playbook_reason),
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
                priority_level=self._execution_degradation_priority(degradation),
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
                priority_level=self._execution_degradation_priority(degradation),
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
        next_actions.extend(
            self._edge_experiment_actions(
                edge_experiment,
                dashboard_payload=dashboard_payload,
                command_context=command_context,
            )
        )
        next_actions.extend(
            self._edge_evolution_actions(
                edge_evolution,
                experiment_context=self._edge_experiment_context(
                    edge_experiment,
                    dashboard_payload=dashboard_payload,
                    command_context=command_context,
                ),
                command_context=command_context,
            )
        )

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

        dedupe_suppressed_actions: list[dict[str, Any]] = []
        filtered_next_actions: list[dict[str, Any]] = []
        for action in next_actions:
            dedupe_reason = self._review_action_dedupe_reason(
                action,
                review_followup_ledger=review_followup_ledger,
            )
            if dedupe_reason:
                suppressed = dict(action)
                suppressed["dedupe_reason"] = str(dedupe_reason.get("reason") or "unknown")
                suppressed["dedupe_message"] = str(dedupe_reason.get("message") or "")
                suppressed["matched_packet"] = self._dict(dedupe_reason.get("matched_packet"))
                dedupe_suppressed_actions.append(suppressed)
                continue
            filtered_next_actions.append(action)
        next_actions = filtered_next_actions
        experiment_context = self._edge_experiment_context(
            edge_experiment,
            dashboard_payload=dashboard_payload,
            command_context=command_context,
        )

        next_actions.sort(
            key=lambda item: (
                -self._priority_rank(str(item.get("priority_level") or "monitor")),
                -self._source_rank(self._normalize_priority_source(str(item.get("source") or ""))),
                str(item.get("action") or ""),
            )
        )
        deferred_experiment_actions: list[dict[str, Any]] = []
        experiment_execution_policy: dict[str, Any] = {
            "mode": "single_active_experiment",
            "reason": "keep one split experiment active until fresh closes advance the next sample target",
            "active_action": "none",
            "active_axis": "none",
            "sample_maturity_state": str(self._dict(experiment_context).get("sample_maturity_state") or "unknown"),
            "next_sample_target_closed_trades": self._int(
                self._dict(experiment_context).get("next_sample_target_closed_trades"),
                0,
            ),
            "remaining_closed_trades_to_next_target": self._int(
                self._dict(experiment_context).get("remaining_closed_trades_to_next_target"),
                0,
            ),
            "deferred_actions": [],
        }
        if experiment_context:
            next_actions, deferred_experiment_actions, experiment_execution_policy = self._enforce_single_experiment_policy(
                next_actions,
                experiment_context=experiment_context,
            )

        top = self._dict(next_actions[0] if next_actions else {})
        capture_context = self._capture_context(opportunity_capture)
        if not top:
            return {
                "available": True,
                "top_action": "continue_runtime_monitoring",
                "top_reason": (
                    "all higher-priority review actions are already covered by fresh or recently stalled ledger packets"
                    if dedupe_suppressed_actions
                    else "no stronger operator action is currently implied by playbook, execution, family, mode, or research signals"
                ),
                "top_action_followup_command": "",
                "priority_level": "monitor",
                "priority_source": "monitor",
                "action_family": "monitor",
                "supporting_signals": [],
                "blocking_signals": [],
                "next_actions": [],
                "capture_context": capture_context,
                "experiment_context": experiment_context,
                "experiment_execution_policy": experiment_execution_policy,
                "deferred_experiment_actions": deferred_experiment_actions,
                "dedupe_suppressed_actions": dedupe_suppressed_actions,
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
        if experiment_context:
            supporting_signals.append(f"edge:{experiment_context.get('edge_state')}")
            supporting_signals.append(
                f"sample_maturity:{experiment_context.get('sample_maturity_state') or 'unknown'}"
            )
            regime_dependency_state = str(experiment_context.get("regime_dependency_state") or "")
            if regime_dependency_state:
                supporting_signals.append(f"regime_dependency:{regime_dependency_state}")
            strongest_regime = str(experiment_context.get("strongest_regime") or "")
            weakest_regime = str(experiment_context.get("weakest_regime") or "")
            if strongest_regime and strongest_regime != "none":
                supporting_signals.append(f"strongest_regime:{strongest_regime}")
            if weakest_regime and weakest_regime != "none":
                supporting_signals.append(f"weakest_regime:{weakest_regime}")
            if self._safe_bool(experiment_context.get("entry_timing_comparison_ready", False)):
                supporting_signals.append(
                    f"entry_timing:{experiment_context.get('entry_timing_preferred_variant')}"
                )
                entry_target = self._dict(experiment_context.get("entry_timing_target"))
                if entry_target.get("symbol"):
                    supporting_signals.append(
                        f"entry_target:{entry_target.get('symbol')}:{entry_target.get('status') or 'UNKNOWN'}"
                    )
            if self._safe_bool(experiment_context.get("execution_style_comparison_ready", False)):
                supporting_signals.append(
                    f"execution_style:{experiment_context.get('execution_style_preferred_variant')}"
                )
                execution_target = self._dict(experiment_context.get("execution_style_target"))
                if execution_target.get("symbol"):
                    supporting_signals.append(
                        f"execution_target:{execution_target.get('symbol')}:{execution_target.get('status') or 'UNKNOWN'}"
                    )
            accepted_focus = self._dict(experiment_context.get("accepted_candidate_focus"))
            if accepted_focus.get("symbol"):
                supporting_signals.append(
                    f"accepted_focus:{accepted_focus.get('symbol')}:{accepted_focus.get('edge_state') or 'n/a'}"
                )
            blocked_focus = self._dict(experiment_context.get("blocked_candidate_focus"))
            if blocked_focus.get("symbol"):
                supporting_signals.append(
                    f"blocked_focus:{blocked_focus.get('symbol')}:{blocked_focus.get('edge_state') or 'n/a'}"
                )
        if edge_evolution:
            supporting_signals.append(f"edge_evolution:{edge_evolution.get('evolution_state') or 'unknown'}")
            promotion_candidate = self._dict(edge_evolution.get("promotion_candidate"))
            if promotion_candidate.get("axis"):
                supporting_signals.append(
                    f"promotion_candidate:{promotion_candidate.get('axis')}:{promotion_candidate.get('preferred_variant') or 'none'}"
                )
            recommendation_strength = str(edge_evolution.get("recommendation_strength") or "")
            if recommendation_strength:
                supporting_signals.append(f"edge_strength:{recommendation_strength}")
        if review_followup_ledger:
            supporting_signals.append(
                f"review_ledger:{review_followup_ledger.get('last_status') or 'none'}:{review_followup_ledger.get('last_action') or 'none'}"
            )
            if int(review_followup_ledger.get("latest_action_streak", 0) or 0) > 0:
                supporting_signals.append(
                    f"review_ledger_streak:{int(review_followup_ledger.get('latest_action_streak', 0) or 0)}"
                )
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

        if not self._safe_bool(dashboard_payload.get("new_entries_allowed"), default=True):
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
        for row in dedupe_suppressed_actions:
            blocking_signals.append(
                f"review_packet_dedupe:{row.get('action') or 'none'}:{row.get('dedupe_reason') or 'unknown'}"
            )
        for row in deferred_experiment_actions:
            blocking_signals.append(
                f"experiment_deferred:{row.get('action') or 'none'}:{row.get('defer_reason') or 'unknown'}"
            )

        return {
            "available": True,
            "top_action": str(top.get("action") or "continue_runtime_monitoring"),
            "top_reason": str(top.get("reason") or ""),
            "top_action_followup_command": str(top.get("followup_command") or ""),
            "priority_level": str(top.get("priority_level") or "monitor"),
            "priority_source": self._normalize_priority_source(str(top.get("source") or "")),
            "action_family": str(top.get("action_family") or "monitor"),
            "supporting_signals": supporting_signals,
            "blocking_signals": blocking_signals,
            "next_actions": next_actions[1:4],
            "capture_context": capture_context,
            "experiment_context": experiment_context,
            "experiment_execution_policy": experiment_execution_policy,
            "deferred_experiment_actions": deferred_experiment_actions[:3],
            "dedupe_suppressed_actions": dedupe_suppressed_actions,
            "advisory_only": True,
        }
