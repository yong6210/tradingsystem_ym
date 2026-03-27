from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import ApprovalState, EntryModel, ExecutionMode, PlanState
from app.db.models import Plan
from app.services.execution.rollout import RolloutPolicyBootstrap

_MODE_RANK = {
    ExecutionMode.SHADOW: 0,
    ExecutionMode.PAPER: 1,
    ExecutionMode.MICRO_LIVE: 2,
    ExecutionMode.LIVE: 3,
}


class ExecutionPlanningService:
    _PAPER_LINEAGE_OVERRIDE_FAMILIES = {"trend_continuation", "sweep_reversal"}
    _PAPER_LINEAGE_OVERRIDE_BLOCKS = {"thesis_duplicate_blocked", "thesis_active_cap_reached"}

    def __init__(
        self,
        settings: Settings | None = None,
        rollout_provider: Any | None = None,
    ):
        self.settings = settings or get_settings()
        self.rollout = rollout_provider or RolloutPolicyBootstrap()

    @staticmethod
    def _csv_set(value: str) -> set[str]:
        items = [item.strip().upper() for item in str(value or "").split(",") if item.strip()]
        return set(items)

    @staticmethod
    def _text(value: Any, default: str = "") -> str:
        return str(value or default)

    @staticmethod
    def _bool(value: Any) -> bool:
        return bool(value)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def coerce_execution_mode(value: Any, default: ExecutionMode = ExecutionMode.SHADOW) -> ExecutionMode:
        try:
            return value if isinstance(value, ExecutionMode) else ExecutionMode(str(value or default.value).upper())
        except ValueError:
            return default

    @classmethod
    def execution_mode_leq(cls, left: ExecutionMode, right: ExecutionMode) -> bool:
        return _MODE_RANK[left] <= _MODE_RANK[right]

    @classmethod
    def min_execution_mode(cls, left: ExecutionMode, right: ExecutionMode) -> ExecutionMode:
        return left if cls.execution_mode_leq(left, right) else right

    def active_execution_mode(self) -> ExecutionMode:
        return self.coerce_execution_mode(self.settings.auto_trading_execution_mode, default=ExecutionMode.SHADOW)

    def allowed_symbols(self) -> set[str]:
        return self._csv_set(self.settings.auto_trading_allowed_symbols)

    def allowed_families(self) -> set[str]:
        return {item.lower() for item in self._csv_set(self.settings.auto_trading_allowed_families)}

    def micro_live_allowed_symbols(self) -> set[str]:
        return self._csv_set(getattr(self.settings, "auto_trading_micro_live_allowed_symbols", ""))

    def micro_live_allowed_families(self) -> set[str]:
        return {item.lower() for item in self._csv_set(getattr(self.settings, "auto_trading_micro_live_allowed_families", ""))}

    def micro_live_allowed_sessions(self) -> set[str]:
        items = [item.strip().lower() for item in str(self.settings.auto_trading_micro_live_allowed_sessions or "").split(",") if item.strip()]
        return set(items)

    @staticmethod
    def _entry_type(entry_model: str) -> str:
        model = str(entry_model or "").upper()
        if model == EntryModel.LIMIT.value:
            return "limit"
        return "stop_market"

    @staticmethod
    def _entry_semantics(entry_model: str) -> str:
        model = str(entry_model or "").upper()
        if model == EntryModel.LIMIT.value:
            return "limit on touch"
        if model == EntryModel.CONFIRM.value:
            return "touch then confirm"
        if model == EntryModel.SWEEP_CONFIRM.value:
            return "sweep then confirm"
        return "server plan required"

    @staticmethod
    def _tp_targets(plan: Plan) -> list[dict[str, Any]]:
        split = dict(plan.split or {})
        return [
            {"label": "TP1", "price": float(plan.tp1), "size_fraction": float(split.get("tp1", 0.0) or 0.0)},
            {"label": "TP2", "price": float(plan.tp2), "size_fraction": float(split.get("tp2", 0.0) or 0.0)},
            {"label": "TP3", "price": float(plan.tp3), "size_fraction": float(split.get("runner", 0.0) or 0.0)},
        ]

    @staticmethod
    def _session_name(candidate: dict[str, Any], operating_lock: dict[str, Any]) -> str:
        current_session = dict(operating_lock or {}).get("current_session") or {}
        if current_session.get("name"):
            return str(current_session["name"]).lower()
        session_guidance = dict(candidate.get("session_guidance") or {})
        return str(session_guidance.get("session_name") or session_guidance.get("state") or "unknown").lower()

    @staticmethod
    def _rollout_reason(allowed_mode: ExecutionMode) -> tuple[str, str]:
        if allowed_mode == ExecutionMode.SHADOW:
            return "rollout_shadow_only", "Rollout policy currently allows shadow-only tracking for this family."
        if allowed_mode == ExecutionMode.PAPER:
            return "paper_rollout_enabled", "Plan is approved for automated paper execution under the current family rollout cap."
        if allowed_mode == ExecutionMode.MICRO_LIVE:
            return "micro_live_rollout_enabled", "Plan is approved for automated micro-live execution under the current rollout cap."
        return "live_rollout_enabled", "Plan is approved for automated live execution under the current rollout cap."

    @staticmethod
    def _playbook_contract(state: ApprovalState, *, reason_code: str, reason: str) -> dict[str, str]:
        if state == ApprovalState.BLOCKED:
            return {
                "playbook_go_no_go": "NO_GO",
                "playbook_code": reason_code or "no_go_execution_blocked",
                "playbook_action": "block_new_entries_until_execution_issue_is_cleared",
                "playbook_message": reason,
            }
        if state == ApprovalState.APPROVED_MANUAL:
            return {
                "playbook_go_no_go": "MANUAL_REVIEW",
                "playbook_code": reason_code or "manual_review_execution_gate",
                "playbook_action": "review_execution_gate_before_submit",
                "playbook_message": reason,
            }
        if state == ApprovalState.APPROVED_SHADOW:
            return {
                "playbook_go_no_go": "GO",
                "playbook_code": reason_code or "go_shadow_only_execution",
                "playbook_action": "record_shadow_only_execution_path",
                "playbook_message": reason,
            }
        return {
            "playbook_go_no_go": "GO",
            "playbook_code": reason_code or "go_execution_auto_submit",
            "playbook_action": "allow_auto_submit",
            "playbook_message": reason,
        }

    @staticmethod
    def _outcome_penalty_reason(code: str, message: str) -> dict[str, Any]:
        return {
            "code": code,
            "message": message,
            "blocking": False,
        }

    @staticmethod
    def _find_axis_bucket(rows: list[dict[str, Any]] | None, bucket: str) -> dict[str, Any]:
        target = str(bucket or "")
        for row in rows or []:
            if str(row.get("bucket") or row.get("key") or "") == target:
                return dict(row)
        return {}

    @staticmethod
    def _find_decomposition_bucket(payload: dict[str, Any] | None, *, axis: str, bucket: str) -> dict[str, Any]:
        rows = list(dict(payload or {}).get("decomposition", {}).get(axis, []) or [])
        target = str(bucket or "")
        for row in rows:
            if str(row.get("key") or "") == target:
                return dict(row)
        return {}

    @staticmethod
    def _thin_sample_from_mode_row(row: dict[str, Any]) -> bool:
        if not row:
            return True
        if str(row.get("confidence") or "low") == "low":
            return True
        sample_note = str(row.get("sample_note") or "").lower()
        return "thin" in sample_note

    def _outcome_approval_penalty(
        self,
        *,
        executable_plan: dict[str, Any],
        candidate_row: dict[str, Any] | None,
        outcome_inputs: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = dict(outcome_inputs or {})
        if not payload:
            return None

        execution_degradation = dict(payload.get("execution_degradation_advisory_summary") or {})
        mode_advisory = dict(payload.get("mode_advisory_summary") or {})
        score_to_outcome = dict(payload.get("score_to_outcome_funnel_summary") or {})
        if not any([execution_degradation, mode_advisory, score_to_outcome]):
            return None

        family = str(executable_plan.get("strategy_family") or "unknown")
        regime = str(dict(executable_plan.get("context_snapshot") or {}).get("regime") or "unknown")
        candidate = dict(candidate_row or {})
        session_name = self._session_name(candidate, dict(candidate.get("operating_lock") or {}))

        family_mode = self._find_axis_bucket(list(mode_advisory.get("family") or []), family)
        regime_mode = self._find_axis_bucket(list(mode_advisory.get("regime") or []), regime)
        session_mode = self._find_axis_bucket(list(mode_advisory.get("session") or []), session_name)

        family_funnel = self._find_decomposition_bucket(score_to_outcome, axis="family", bucket=family)
        regime_funnel = self._find_decomposition_bucket(score_to_outcome, axis="regime", bucket=regime)
        session_funnel = self._find_decomposition_bucket(score_to_outcome, axis="session", bucket=session_name)

        degradation_status = str(execution_degradation.get("status") or "healthy").lower()
        mode_rows = [row for row in [family_mode, regime_mode, session_mode] if row]
        adverse_mode_rows = [
            row
            for row in mode_rows
            if str(row.get("advisory_state") or "") in {"watch", "research_only"} and not self._thin_sample_from_mode_row(row)
        ]

        reason_codes: list[str] = []
        if degradation_status in {"watch", "manual_review"}:
            reason_codes.append(f"execution_degradation:{degradation_status}")

        for axis, row in (("family", family_mode), ("regime", regime_mode), ("session", session_mode)):
            advisory_state = str(row.get("advisory_state") or "")
            if advisory_state in {"watch", "research_only"} and not self._thin_sample_from_mode_row(row):
                reason_codes.append(f"mode_advisory:{axis}:{advisory_state}")

        post_cost_reason = None
        post_cost_rate = None
        post_cost_closed = 0
        for axis, row in (("family", family_funnel), ("regime", regime_funnel), ("session", session_funnel)):
            closed = int(row.get("closed", 0) or 0)
            rate = float(row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
            if closed >= 4 and rate <= 0.3:
                post_cost_reason = f"post_cost_conversion:weak_{axis}_alignment"
                post_cost_rate = rate
                post_cost_closed = closed
                break

        if post_cost_reason:
            reason_codes.append(post_cost_reason)

        deduped_reason_codes = list(dict.fromkeys(reason_codes))
        if not deduped_reason_codes:
            return {
                "available": True,
                "status": "healthy",
                "penalty_tier": "none",
                "applied": False,
                "summary": "outcome-aware approval penalty found no material degradation or post-cost conversion issue",
                "reason_codes": [],
                "source_summary": {
                    "execution_degradation_status": degradation_status or "healthy",
                    "mode_advisory_state": str((adverse_mode_rows[:1] or [{}])[0].get("advisory_state") or "keep_current_mode"),
                    "baseline_cost_profitable_rate_from_closed": float(
                        dict(score_to_outcome.get("historical_execution_outcomes") or {}).get(
                            "baseline_cost_profitable_rate_from_closed",
                            0.0,
                        )
                        or 0.0
                    ),
                },
            }

        status = "watch"
        penalty_tier = "reason_only"
        if degradation_status == "manual_review" or (post_cost_reason and adverse_mode_rows):
            status = "manual_review"
            penalty_tier = "downgrade_to_manual"

        summary = "execution degradation and post-cost outcome signals require closer review before new live entries"
        if penalty_tier == "downgrade_to_manual":
            summary = "execution degradation and post-cost outcome signals require manual review before new live entries"

        return {
            "available": True,
            "status": status,
            "penalty_tier": penalty_tier,
            "applied": True,
            "summary": summary,
            "reason_codes": deduped_reason_codes,
            "source_summary": {
                "execution_degradation_status": degradation_status or "healthy",
                "mode_advisory_state": str((adverse_mode_rows[:1] or [{}])[0].get("advisory_state") or "keep_current_mode"),
                "baseline_cost_profitable_rate_from_closed": (
                    float(post_cost_rate)
                    if isinstance(post_cost_rate, float)
                    else float(
                        dict(score_to_outcome.get("historical_execution_outcomes") or {}).get(
                            "baseline_cost_profitable_rate_from_closed",
                            0.0,
                        )
                        or 0.0
                    )
                ),
                "post_cost_closed": int(post_cost_closed),
            },
        }

    def build_executable_plan(
        self,
        *,
        plan: Plan,
        context: Any | None,
        candidate_row: dict[str, Any] | None,
        execution_mode: ExecutionMode | None = None,
    ) -> dict[str, Any]:
        validity = dict(plan.validity or {})
        candidate = dict(candidate_row or {})
        effective_mode = execution_mode or self.active_execution_mode()
        recommended_risk_r = float(validity.get("recommended_risk_r", candidate.get("recommended_risk_r", 0.0)) or 0.0)
        family = self._text(validity.get("strategy_family"), "legacy_zone_plan").lower()
        tf = self._text(plan.timeframe, "5m")
        valid_for_seconds = max(
            0,
            int((self._utc(plan.valid_until) - datetime.now(timezone.utc)).total_seconds()),
        )
        entry_model = self._text(plan.entry_model)
        entry_type = self._entry_type(entry_model)
        entry_trigger_price = float(plan.entry_price) if entry_type != "limit" else None
        entry_limit_price = float(plan.entry_price) if entry_type == "limit" else None
        timeout_seconds = min(max(valid_for_seconds, 0), 900 if entry_type == "limit" else 1200)
        scorecard = dict(validity.get("strategy_scorecard") or {})
        return {
            "plan_id": plan.plan_id,
            "symbol": plan.symbol,
            "tf": tf,
            "strategy_version": plan.strategy_version,
            "strategy_family": family,
            "strategy_mode": self._text(validity.get("strategy_mode"), getattr(self.settings.strategy_mode, "value", "A_ONLY")),
            "execution_mode": effective_mode.value,
            "thesis_fingerprint": validity.get("thesis_fingerprint") or candidate.get("thesis_fingerprint"),
            "thesis_cluster_id": self._text(validity.get("thesis_cluster_id") or candidate.get("thesis_cluster_id")),
            "thesis_primary_symbol": self._text(
                validity.get("thesis_primary_symbol") or candidate.get("thesis_primary_symbol") or plan.symbol
            ),
            "direction": plan.direction,
            "setup_grade": self._text(validity.get("strategy_grade"), candidate.get("strategy_grade") or "B"),
            "setup_score": float(
                validity.get("strategy_family_score", validity.get("confluence_score", candidate.get("final_rank_score", 0.0)))
                or 0.0
            ),
            "entry_model": entry_model,
            "entry_type": entry_type,
            "entry_semantics": self._entry_semantics(entry_model),
            "entry_trigger_price": entry_trigger_price,
            "entry_limit_price": entry_limit_price,
            "entry_timeout_seconds": timeout_seconds,
            "cancel_if_not_filled": True,
            "stop_price": float(plan.sl),
            "tp_targets": self._tp_targets(plan),
            "recommended_risk_r": recommended_risk_r,
            "max_position_notional": round(max(0.0, recommended_risk_r) * float(self.settings.auto_trading_notional_per_r), 4),
            "expected_fee_bps": float(self.settings.taker_fee_bps if entry_type != "limit" else self.settings.maker_fee_bps),
            "max_slippage_bps": float(self.settings.auto_trading_max_slippage_bps),
            "valid_from": self._utc(plan.valid_from),
            "valid_until": self._utc(plan.valid_until),
            "kill_if_transition_lock": True,
            "kill_if_regime_changes": True,
            "expected_summary": {
                "expected_win_prob": float(candidate.get("expected_win_prob", validity.get("expected_win_prob", 0.0)) or 0.0),
                "expected_ev_r": float(candidate.get("expected_ev_r", validity.get("expected_ev_r", plan.ev)) or 0.0),
                "expected_source": "runtime_candidate_overlay",
                "expected_summary": self._text(candidate.get("expected_summary"), validity.get("expected_summary", "")),
            },
            "context_snapshot": {
                "regime": self._text(validity.get("regime"), candidate.get("regime") or "range"),
                "risk_label": self._text((candidate.get("session_guidance") or {}).get("risk_label"), candidate.get("risk_reason") or "normal"),
                "transition_state": self._text(validity.get("transition_state"), getattr(context, "transition_state", "none")),
                "session_guidance": self._text((candidate.get("session_guidance") or {}).get("state"), "unknown"),
                "portfolio_headroom_state": "open" if self._bool(candidate.get("accepted")) else "constrained",
                "deployment_go_no_go": self._text(candidate.get("deployment_go_no_go"), "MANUAL_REVIEW"),
                "block_reason": self._text(candidate.get("block_reason")),
                "block_reason_message": self._text(candidate.get("block_reason_message")),
            },
            "mirror_plan_note": "chart score != deployment approval; chart plan != live order instruction",
            "strategy_scorecard_buckets": dict(scorecard.get("buckets") or validity.get("strategy_scorecard_buckets") or {}),
            "strategy_scorecard_raw_components": dict(scorecard.get("raw_components") or validity.get("strategy_scorecard_raw_components") or {}),
        }

    def approve(
        self,
        *,
        plan: Plan,
        executable_plan: dict[str, Any],
        candidate_row: dict[str, Any] | None,
        metrics: dict[str, Any],
        requested_execution_mode: ExecutionMode | None = None,
        strict_requested_mode: bool = False,
        safety_state: dict[str, Any] | None = None,
        current_exposure_count: int = 0,
        daily_new_entry_count: int = 0,
        paper_lineage_override: bool = False,
        outcome_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        candidate = dict(candidate_row or {})
        safety = dict(safety_state or {})
        requested_mode = self.coerce_execution_mode(requested_execution_mode or executable_plan.get("execution_mode"))
        family = str(executable_plan.get("strategy_family") or "legacy_zone_plan").lower()
        rollout_policy = self.rollout.get(family)
        allowed_execution_mode = self.min_execution_mode(requested_mode, rollout_policy.max_execution_mode)

        symbol = str(plan.symbol or "").upper()
        metrics_grade = str(metrics.get("grade") or "F").upper()
        metrics_recommendation = str(metrics.get("recommendation") or "do-not-deploy")
        risk_state = str(metrics.get("risk_state") or "CLOSED")
        operating_lock = dict(metrics.get("operating_lock") or {})
        deployment_go_no_go = str(candidate.get("deployment_go_no_go") or "NO_GO")
        deployment_code = str(candidate.get("deployment_code") or "no_go_runtime_candidate_missing")
        deployment_message = str(candidate.get("deployment_message") or "NO_GO: runtime candidate is unavailable.")
        block_reason = str(candidate.get("block_reason") or "")
        block_reason_message = str(candidate.get("block_reason_message") or deployment_message)
        risk_reason = str(metrics.get("risk_reason") or candidate.get("risk_reason") or "normal")
        session_guidance = dict(candidate.get("session_guidance") or {})
        setup_score = float(executable_plan.get("setup_score", 0.0) or 0.0)
        recommended_risk_r = float(executable_plan.get("recommended_risk_r", 0.0) or 0.0)
        setup_grade = str(executable_plan.get("setup_grade") or "").upper()
        session_name = self._session_name(candidate, operating_lock)
        requested_mode_exceeds_cap = _MODE_RANK[requested_mode] > _MODE_RANK[rollout_policy.max_execution_mode]
        override_applied = False
        override_reason = ""
        override_source = ""
        outcome_approval_penalty = self._outcome_approval_penalty(
            executable_plan=executable_plan,
            candidate_row=candidate_row,
            outcome_inputs=outcome_inputs,
        )

        thesis_rejected_reason = str(candidate.get("thesis_rejected_reason") or "")
        override_block_candidate = block_reason in self._PAPER_LINEAGE_OVERRIDE_BLOCKS or thesis_rejected_reason == "duplicate_active_thesis"
        if (
            paper_lineage_override
            and requested_mode == ExecutionMode.PAPER
            and family in self._PAPER_LINEAGE_OVERRIDE_FAMILIES
            and setup_grade == "A"
            and override_block_candidate
        ):
            override_applied = True
            override_source = "paper_lineage_override"
            if block_reason == "thesis_active_cap_reached":
                override_reason = "paper lineage override bypassed thesis active-cap block for eligible A-grade PAPER sampling."
            else:
                override_reason = "paper lineage override bypassed thesis duplicate block for eligible A-grade PAPER sampling."
        paper_lineage_sampling_mode = override_applied and requested_mode == ExecutionMode.PAPER
        lineage_override_extra_reasons: list[dict[str, Any]] = []

        effective_block_reason = "" if override_applied else block_reason
        effective_block_reason_message = "" if override_applied else block_reason_message

        def result(state: ApprovalState, reason_code: str, reason: str, extra_reasons: list[dict[str, Any]] | None = None) -> dict[str, Any]:
            final_state = state
            final_reason_code = reason_code
            final_reason = reason
            applied_penalty = dict(outcome_approval_penalty or {})
            if (
                state == ApprovalState.APPROVED_AUTO
                and not paper_lineage_sampling_mode
                and applied_penalty
                and bool(applied_penalty.get("available"))
                and str(applied_penalty.get("penalty_tier") or "") == "downgrade_to_manual"
            ):
                final_state = ApprovalState.APPROVED_MANUAL
                final_reason_code = "outcome_penalty_manual_review"
                final_reason = str(applied_penalty.get("summary") or reason)

            playbook = self._playbook_contract(final_state, reason_code=final_reason_code, reason=final_reason)
            approval_reasons = [{"code": reason_code, "message": reason, "blocking": state == ApprovalState.BLOCKED}]
            for item in extra_reasons or []:
                approval_reasons.append(
                    {
                        "code": str(item.get("code") or ""),
                        "message": str(item.get("message") or ""),
                        "blocking": bool(item.get("blocking")),
                    }
                )
            if applied_penalty and bool(applied_penalty.get("available")):
                for code in list(applied_penalty.get("reason_codes") or []):
                    approval_reasons.append(
                        self._outcome_penalty_reason(
                            code=str(code),
                            message=str(applied_penalty.get("summary") or "outcome-aware approval penalty applied"),
                        )
                    )
            return {
                "plan_id": plan.plan_id,
                "symbol": plan.symbol,
                "approval_state": final_state.value,
                "allowed_execution_mode": allowed_execution_mode.value,
                "strategy_mode": executable_plan.get("strategy_mode", getattr(self.settings.strategy_mode, "value", "A_ONLY")),
                "execution_mode": requested_mode.value,
                "deployment_go_no_go": deployment_go_no_go,
                "deployment_code": deployment_code,
                "deployment_message": deployment_message,
                "playbook_go_no_go": playbook["playbook_go_no_go"],
                "playbook_code": playbook["playbook_code"],
                "playbook_action": playbook["playbook_action"],
                "playbook_message": playbook["playbook_message"],
                "approval_reasons": approval_reasons,
                "approved_at": now,
                "expires_at": self._utc(plan.valid_until),
                "validation_grade": metrics_grade,
                "validation_recommendation": metrics_recommendation,
                "risk_state": risk_state,
                "risk_reason": risk_reason,
                "operating_lock": operating_lock,
                "session_guidance": session_guidance,
                "block_reason": effective_block_reason,
                "block_reason_message": effective_block_reason_message,
                "paper_lineage_override_applied": override_applied,
                "paper_lineage_override_reason": override_reason,
                "paper_lineage_override_source": override_source,
                "top_candidate": bool(candidate),
                "auto_trading_enabled": bool(self.settings.auto_trading_enabled),
                "rollout_policy": rollout_policy.to_dict(),
                "safety_state": safety,
                "outcome_approval_penalty": applied_penalty or None,
            }

        if plan.state not in {PlanState.PLANNED.value, PlanState.ARMED.value}:
            return result(
                ApprovalState.BLOCKED,
                "stale_plan_state",
                f"Plan state {plan.state} is not eligible for a new entry.",
            )
        if self._utc(plan.valid_until) <= now:
            return result(ApprovalState.BLOCKED, "stale_plan_expired", "Plan validity already expired.")
        if self.settings.auto_trading_close_only:
            return result(ApprovalState.BLOCKED, "close_only_mode", "Close-only mode is active; no new entries are allowed.")
        if not bool(safety.get("new_entry_allowed", True)):
            return result(
                ApprovalState.BLOCKED,
                str(safety.get("blocking_reason_code") or "safety_lock_active"),
                str(safety.get("blocking_reason_message") or "A safety lock blocks new entries."),
            )
        if not candidate:
            return result(ApprovalState.BLOCKED, "no_runtime_candidate", "No runtime-assessed candidate exists for this plan.")
        if deployment_go_no_go == "NO_GO":
            return result(ApprovalState.BLOCKED, deployment_code or "runtime_no_go", deployment_message)
        if bool(operating_lock.get("active")) or risk_state == "CLOSED":
            return result(ApprovalState.BLOCKED, "runtime_gate_closed", deployment_message or "Runtime gate is closed.")
        if not override_applied and (
            candidate.get("thesis_rejected_reason") == "duplicate_active_thesis" or block_reason == "thesis_duplicate_blocked"
        ):
            return result(
                ApprovalState.BLOCKED,
                "thesis_duplicate_blocked",
                block_reason_message or "An active candidate with the same thesis already exists.",
            )
        if effective_block_reason:
            effective_message = effective_block_reason_message or "Plan is blocked by runtime portfolio gate."
            return result(
                ApprovalState.BLOCKED,
                effective_block_reason,
                effective_message,
            )
        if symbol and self.allowed_symbols() and symbol not in self.allowed_symbols():
            if not paper_lineage_sampling_mode:
                return result(
                    ApprovalState.BLOCKED,
                    "symbol_not_live_enabled",
                    f"{symbol} is not in the current auto-trading allowlist.",
                )
            lineage_override_extra_reasons.append(
                {
                    "code": "paper_lineage_override_bypassed_symbol_allowlist",
                    "message": f"PAPER lineage sampling bypassed the auto-trading symbol allowlist for {symbol}.",
                    "blocking": False,
                }
            )
        if family and self.allowed_families() and family not in self.allowed_families():
            if not paper_lineage_sampling_mode:
                return result(
                    ApprovalState.BLOCKED,
                    "family_not_live_enabled",
                    f"{family} is not in the current auto-trading family allowlist.",
                )
            lineage_override_extra_reasons.append(
                {
                    "code": "paper_lineage_override_bypassed_family_allowlist",
                    "message": f"PAPER lineage sampling bypassed the auto-trading family allowlist for {family}.",
                    "blocking": False,
                }
            )
        if executable_plan.get("strategy_mode") == "RESEARCH":
            return result(
                ApprovalState.APPROVED_SHADOW,
                "mode_policy_research_only",
                "Research mode is shadow-only by policy.",
            )
        if requested_mode == ExecutionMode.LIVE and strict_requested_mode:
            return result(
                ApprovalState.BLOCKED,
                "live_mode_not_enabled",
                "Full LIVE mode is not enabled yet; MICRO_LIVE is the highest supported live path.",
            )
        if strict_requested_mode and requested_mode_exceeds_cap:
            return result(
                ApprovalState.BLOCKED,
                "rollout_mode_cap_exceeded",
                f"Requested execution mode {requested_mode.value} exceeds the family rollout cap {rollout_policy.max_execution_mode.value}.",
            )
        if rollout_policy.allowed_sessions and session_name not in set(rollout_policy.allowed_sessions):
            return result(
                ApprovalState.BLOCKED,
                "rollout_session_not_allowed",
                f"Current session {session_name} is outside the allowed rollout sessions for {family}.",
            )
        if self.settings.auto_trading_require_validation_go and metrics_recommendation == "do-not-deploy":
            if not paper_lineage_sampling_mode:
                return result(
                    ApprovalState.BLOCKED,
                    "validation_do_not_deploy",
                    "Validation recommendation is do-not-deploy.",
                )
            lineage_override_extra_reasons.append(
                {
                    "code": "paper_lineage_override_bypassed_validation_do_not_deploy",
                    "message": "PAPER lineage sampling bypassed the validation do-not-deploy gate while edge proof remains in sample-building mode.",
                    "blocking": False,
                }
            )
        if requested_mode in {ExecutionMode.LIVE, ExecutionMode.MICRO_LIVE} and not rollout_policy.live_enabled:
            return result(
                ApprovalState.BLOCKED,
                "family_live_rollout_disabled",
                f"{family} is not enabled for live rollout.",
            )
        if requested_mode == ExecutionMode.MICRO_LIVE:
            strategy_mode = str(executable_plan.get("strategy_mode") or "")
            if strategy_mode != "A_ONLY":
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_requires_a_only",
                    "MICRO_LIVE is limited to A_ONLY strategy mode.",
                )
            micro_live_symbols = self.micro_live_allowed_symbols()
            if micro_live_symbols and symbol not in micro_live_symbols:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_symbol_not_allowed",
                    f"{symbol} is outside the MICRO_LIVE symbol allowlist.",
                )
            micro_live_families = self.micro_live_allowed_families()
            if micro_live_families and family not in micro_live_families:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_family_not_allowed",
                    f"{family} is outside the MICRO_LIVE family allowlist.",
                )
            micro_live_sessions = self.micro_live_allowed_sessions()
            if micro_live_sessions and session_name not in micro_live_sessions:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_session_not_allowed",
                    f"Current session {session_name} is outside the MICRO_LIVE session allowlist.",
                )
            if current_exposure_count >= int(self.settings.auto_trading_micro_live_max_concurrent_positions):
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_position_cap_reached",
                    f"Open exposure count {current_exposure_count} reached the MICRO_LIVE concurrent position cap.",
                )
            if daily_new_entry_count >= int(self.settings.auto_trading_micro_live_max_daily_new_entries):
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_daily_entry_cap_reached",
                    f"Today's new entry count {daily_new_entry_count} reached the MICRO_LIVE daily cap.",
                )
        if recommended_risk_r > float(rollout_policy.max_risk_r) + 1e-9 and rollout_policy.max_risk_r > 0.0:
            return result(
                ApprovalState.APPROVED_MANUAL,
                "rollout_risk_cap_exceeded",
                f"Recommended risk {recommended_risk_r:.2f}R exceeds the family rollout cap {rollout_policy.max_risk_r:.2f}R.",
            )
        if setup_score < float(rollout_policy.min_quality_score):
            return result(
                ApprovalState.APPROVED_MANUAL,
                "rollout_min_quality_not_met",
                f"Setup score {setup_score:.1f} is below the family rollout minimum {rollout_policy.min_quality_score:.1f}.",
            )
        if self.settings.auto_trading_require_validation_go:
            if allowed_execution_mode == ExecutionMode.LIVE and metrics_grade != "A":
                return result(
                    ApprovalState.APPROVED_MANUAL,
                    "validation_live_requires_grade_a",
                    "LIVE mode requires validation grade A.",
                )
            if allowed_execution_mode == ExecutionMode.MICRO_LIVE and metrics_grade not in {"A", "B"}:
                return result(
                    ApprovalState.APPROVED_MANUAL,
                    "validation_micro_live_requires_grade_ab",
                    "MICRO_LIVE requires validation grade A or B.",
                )
        if deployment_go_no_go == "MANUAL_REVIEW" or risk_state == "THROTTLED":
            return result(
                ApprovalState.APPROVED_MANUAL,
                "manual_review_required",
                deployment_message or "Manual review is required before submit.",
            )
        if not self.settings.auto_trading_enabled:
            return result(
                ApprovalState.APPROVED_SHADOW,
                "auto_trading_disabled",
                "Auto trading is globally disabled, so this plan is shadow-only.",
            )
        if allowed_execution_mode == ExecutionMode.SHADOW:
            return result(
                ApprovalState.APPROVED_SHADOW,
                "rollout_shadow_only",
                "Current rollout stage is shadow-only for this family.",
            )

        rollout_code, rollout_message = self._rollout_reason(allowed_execution_mode)
        extra_reasons: list[dict[str, Any]] = []
        if override_applied:
            extra_reasons.append(
                {
                    "code": "paper_lineage_override_applied",
                    "message": override_reason,
                    "blocking": False,
                }
            )
        extra_reasons.extend(lineage_override_extra_reasons)
        if requested_mode_exceeds_cap and not strict_requested_mode:
            extra_reasons.append(
                {
                    "code": "rollout_mode_capped",
                    "message": f"Requested/global mode was capped to {allowed_execution_mode.value} by family rollout policy.",
                    "blocking": False,
                }
            )
        if (
            paper_lineage_sampling_mode
            and outcome_approval_penalty
            and bool(outcome_approval_penalty.get("available"))
            and str(outcome_approval_penalty.get("penalty_tier") or "") == "downgrade_to_manual"
        ):
            extra_reasons.append(
                {
                    "code": "paper_lineage_override_retained_paper_auto_submit",
                    "message": "PAPER lineage sampling kept auto-submit eligibility despite live-entry outcome penalties.",
                    "blocking": False,
                }
            )
        return result(ApprovalState.APPROVED_AUTO, rollout_code, rollout_message, extra_reasons=extra_reasons)
