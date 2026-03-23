from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.enums import ApprovalState, ExecutionMode, PlanState, SubmitDecision
from app.db.models import OrderIntent, OrderSubmission, Plan
from app.repositories.execution import OrderIntentRepository, OrderSubmissionRepository, PlanRepository
from app.services.execution.approval import ExecutionPlanningService
from app.services.thesis_fingerprint import ThesisFingerprintService


class OrderIntentService:
    def __init__(
        self,
        *,
        plan_repo: PlanRepository,
        intent_repo: OrderIntentRepository,
        submission_repo: OrderSubmissionRepository | None = None,
        approval_loader: Callable[[str, ExecutionMode, bool], dict],
        exposure_loader: Callable[[], list[Plan]],
        settings: Settings | None = None,
    ):
        self.plan_repo = plan_repo
        self.intent_repo = intent_repo
        self.submission_repo = submission_repo
        self.approval_loader = approval_loader
        self.exposure_loader = exposure_loader
        self.settings = settings or get_settings()
        self.thesis = ThesisFingerprintService(self.settings)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _is_stale(plan: Plan) -> bool:
        return plan.state not in {PlanState.PLANNED.value, PlanState.ARMED.value} or OrderIntentService._utc(plan.valid_until) <= datetime.now(timezone.utc)

    @staticmethod
    def _submission_keeps_thesis_open(submission: OrderSubmission | None) -> bool:
        if submission is None:
            return True
        return str(submission.state or "") in {
            "CREATED",
            "SUBMITTED",
            "ACKNOWLEDGED",
            "PARTIALLY_FILLED",
            "FILLED",
        }

    def _dedupe_via_open_intents(self, *, plan: Plan, fingerprint: dict) -> dict | None:
        validity = dict(plan.validity or {})
        current_primary_symbol = str(validity.get("thesis_primary_symbol") or plan.symbol or "").upper()
        recent_intents = self.intent_repo.list_recent(limit=500)
        for intent in recent_intents:
            if intent.plan_id == plan.plan_id:
                continue
            if str(intent.submit_decision or "") != SubmitDecision.SUBMIT.value:
                continue

            other_plan = self.plan_repo.get(intent.plan_id)
            if other_plan is not None and other_plan.state in {
                PlanState.TRIGGERED.value,
                PlanState.ENTERED.value,
                PlanState.PARTIAL_EXIT.value,
                PlanState.ARMED.value,
            }:
                plan_still_open = True
            else:
                plan_still_open = False

            latest_submission = self.submission_repo.latest_for_intent(intent.intent_id) if self.submission_repo else None
            if not plan_still_open and not self._submission_keeps_thesis_open(latest_submission):
                continue

            other_fingerprint = dict(intent.thesis_fingerprint or {})
            if not other_fingerprint:
                continue
            other_payload = dict(intent.payload or {})
            other_executable_plan = dict(other_payload.get("executable_plan") or {})
            other_primary_symbol = str(
                other_executable_plan.get("thesis_primary_symbol")
                or intent.symbol
                or ""
            ).upper()
            same_execution_group = str(intent.symbol or "").upper() == str(plan.symbol or "").upper() or (
                current_primary_symbol and other_primary_symbol and current_primary_symbol == other_primary_symbol
            )
            if not same_execution_group:
                continue
            if not self.thesis.same_thesis(fingerprint, other_fingerprint):
                continue

            return {
                "status": "duplicate_active_thesis",
                "matched_plan_id": intent.plan_id,
                "matched_intent_id": intent.intent_id,
                "matched_submission_id": latest_submission.submission_id if latest_submission else None,
                "matched_symbol": intent.symbol,
                "cluster_id": self.thesis.thesis_cluster_id(fingerprint),
                "source": "open_intent",
            }
        return None

    def _dedupe_result(self, plan: Plan) -> dict:
        fingerprint = self.thesis.build_from_plan(plan)
        from_open_intents = self._dedupe_via_open_intents(plan=plan, fingerprint=fingerprint)
        if from_open_intents is not None:
            return from_open_intents

        for exposure in self.exposure_loader():
            if exposure.plan_id == plan.plan_id:
                continue
            if exposure.state not in {
                PlanState.ARMED.value,
                PlanState.TRIGGERED.value,
                PlanState.ENTERED.value,
                PlanState.PARTIAL_EXIT.value,
            }:
                continue
            if self.thesis.same_thesis(fingerprint, self.thesis.build_from_plan(exposure)):
                return {
                    "status": "duplicate_active_thesis",
                    "matched_plan_id": exposure.plan_id,
                    "matched_intent_id": None,
                    "matched_submission_id": None,
                    "matched_symbol": exposure.symbol,
                    "cluster_id": self.thesis.thesis_cluster_id(fingerprint),
                    "source": "active_plan",
                }
        return {
            "status": "unique",
            "matched_plan_id": None,
            "matched_intent_id": None,
            "matched_submission_id": None,
            "matched_symbol": None,
            "cluster_id": self.thesis.thesis_cluster_id(fingerprint),
            "source": "none",
        }

    @staticmethod
    def _quality_snapshot(*, approval: dict, executable_plan: dict) -> dict:
        expected_summary = dict(executable_plan.get("expected_summary") or {})
        return {
            "validation_grade": str(approval.get("validation_grade") or ""),
            "validation_recommendation": str(approval.get("validation_recommendation") or ""),
            "risk_state": str(approval.get("risk_state") or ""),
            "risk_reason": str(approval.get("risk_reason") or ""),
            "setup_grade": str(executable_plan.get("setup_grade") or ""),
            "setup_score": float(executable_plan.get("setup_score", 0.0) or 0.0),
            "recommended_risk_r": float(executable_plan.get("recommended_risk_r", 0.0) or 0.0),
            "expected_ev_r": float(expected_summary.get("expected_ev_r", 0.0) or 0.0),
        }

    @classmethod
    def _json_safe(cls, value):
        if isinstance(value, datetime):
            current = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            return current.astimezone(timezone.utc).isoformat()
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._json_safe(item) for item in value]
        return value

    @staticmethod
    def _decision_for(
        *,
        execution_mode: ExecutionMode,
        approval_state: ApprovalState,
        stale: bool,
        duplicate: bool,
        paper_lineage_override: bool = False,
        dedupe_source: str = "",
        approval_reason_code: str = "",
    ) -> tuple[SubmitDecision, str, str]:
        if stale:
            return (
                SubmitDecision.SKIP_STALE_PLAN,
                "stale_plan",
                "Plan is stale or expired, so no submit intent will be created.",
            )
        if duplicate and not (
            paper_lineage_override
            and execution_mode == ExecutionMode.PAPER
            and str(dedupe_source or "") == "active_plan"
        ):
            return (
                SubmitDecision.SKIP_DUPLICATE,
                "duplicate_active_thesis",
                "An active thesis-equivalent plan already exists, so submit is skipped.",
            )
        if approval_state == ApprovalState.BLOCKED:
            reason_code = str(approval_reason_code or "")
            if reason_code.startswith("kill_switch"):
                return (
                    SubmitDecision.SKIP_KILL_SWITCH,
                    reason_code or "kill_switch_active",
                    "Kill switch is active, so submit is skipped.",
                )
            if "reconciliation" in reason_code:
                return (
                    SubmitDecision.SKIP_RECONCILIATION_LOCK,
                    reason_code or "reconciliation_lock_active",
                    "A reconciliation hard lock blocks new entries for this plan.",
                )
            if "close_only" in reason_code:
                return (
                    SubmitDecision.SKIP_CLOSE_ONLY,
                    reason_code or "close_only_active",
                    "Close-only mode is active, so new entries are skipped.",
                )
            return (
                SubmitDecision.SKIP_BLOCKED,
                "approval_blocked",
                "Execution approval is blocked for this plan.",
            )
        if approval_state == ApprovalState.APPROVED_MANUAL:
            return (
                SubmitDecision.SKIP_MANUAL_ONLY,
                "manual_review_required",
                "Execution approval requires manual review before submit.",
            )
        if approval_state == ApprovalState.APPROVED_SHADOW or execution_mode == ExecutionMode.SHADOW:
            return (
                SubmitDecision.SKIP_SHADOW_ONLY,
                "shadow_only",
                "Execution path is shadow-only, so submit is skipped.",
            )
        return (
            SubmitDecision.SUBMIT,
            "submit_ready",
            f"Intent is approved for {execution_mode.value} submit.",
        )

    def create_intent(
        self,
        *,
        plan_id: str,
        execution_mode: ExecutionMode,
        paper_lineage_override: bool = False,
    ) -> OrderIntent:
        plan = self.plan_repo.get(plan_id)
        if plan is None:
            raise ValueError("plan_not_found")

        requested_mode = ExecutionPlanningService.coerce_execution_mode(execution_mode, default=ExecutionMode.SHADOW)
        approval_bundle = self.approval_loader(
            plan_id,
            requested_mode,
            paper_lineage_override=paper_lineage_override,
        )
        approval = dict(approval_bundle["approval"])
        executable_plan = dict(approval_bundle["executable_plan"])
        approval_state = ApprovalState(str(approval.get("approval_state") or ApprovalState.BLOCKED.value))
        stale = self._is_stale(plan)
        dedupe_result = self._dedupe_result(plan)
        duplicate = dedupe_result.get("status") == "duplicate_active_thesis"
        dedupe_source = str(dedupe_result.get("source") or "")
        override_applied = bool(approval.get("paper_lineage_override_applied"))
        override_active_plan_duplicate = (
            override_applied
            and requested_mode == ExecutionMode.PAPER
            and dedupe_source == "active_plan"
        )
        decision, reason_code, reason_message = self._decision_for(
            execution_mode=requested_mode,
            approval_state=approval_state,
            stale=stale,
            duplicate=duplicate,
            paper_lineage_override=override_active_plan_duplicate,
            dedupe_source=dedupe_source,
            approval_reason_code=str(approval.get("playbook_code") or ""),
        )

        if stale:
            reason_message = "Plan is no longer valid for a new entry."
        elif duplicate and override_active_plan_duplicate:
            reason_code = str(approval.get("paper_lineage_override_reason") or "paper_lineage_override_applied")
            reason_message = (
                str(approval.get("paper_lineage_override_reason") or "")
                or "PAPER lineage override allowed an active-plan thesis duplicate for sample collection."
            )
        elif duplicate:
            matched_plan = dedupe_result.get("matched_plan_id")
            reason_message = f"Duplicate thesis detected against active plan {matched_plan}."
        elif decision == SubmitDecision.SKIP_BLOCKED:
            reason_code = str(approval.get("playbook_code") or approval.get("approval_reasons", [{}])[0].get("code") or reason_code)
            reason_message = str(approval.get("playbook_message") or reason_message)
        elif decision == SubmitDecision.SKIP_MANUAL_ONLY:
            reason_code = str(approval.get("playbook_code") or reason_code)
            reason_message = str(approval.get("playbook_message") or reason_message)
        elif decision == SubmitDecision.SKIP_SHADOW_ONLY:
            reason_code = str(approval.get("playbook_code") or reason_code)
            reason_message = str(approval.get("playbook_message") or reason_message)

        quality_snapshot = self._quality_snapshot(approval=approval, executable_plan=executable_plan)
        row = OrderIntent(
            intent_id=f"intent_{uuid4().hex[:20]}",
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            strategy_family=str(executable_plan.get("strategy_family") or "legacy_zone_plan"),
            execution_mode=requested_mode.value,
            approval_state=approval_state.value,
            submit_decision=decision.value,
            decision_reason_code=reason_code,
            decision_reason_message=reason_message,
            thesis_fingerprint=dict(executable_plan.get("thesis_fingerprint") or {}),
            dedupe_result=dedupe_result,
            session_guidance=dict(approval.get("session_guidance") or {}),
            quality_snapshot=quality_snapshot,
            approval_snapshot=self._json_safe(approval),
            payload={
                "executable_plan": self._json_safe(executable_plan),
                "requested_execution_mode": requested_mode.value,
                "intent_snapshot": {
                    "allowed_execution_mode": str(approval.get("allowed_execution_mode") or ""),
                    "deployment_go_no_go": str(approval.get("deployment_go_no_go") or ""),
                    "deployment_code": str(approval.get("deployment_code") or ""),
                    "playbook_go_no_go": str(approval.get("playbook_go_no_go") or ""),
                    "playbook_code": str(approval.get("playbook_code") or ""),
                    "playbook_action": str(approval.get("playbook_action") or ""),
                    "playbook_message": str(approval.get("playbook_message") or ""),
                    "paper_lineage_override_applied": bool(approval.get("paper_lineage_override_applied")),
                    "paper_lineage_override_reason": str(approval.get("paper_lineage_override_reason") or ""),
                    "paper_lineage_override_source": str(approval.get("paper_lineage_override_source") or ""),
                    "source_of_truth_hint": "execution_approval_snapshot",
                },
            },
        )
        self.intent_repo.add(row)
        return row
