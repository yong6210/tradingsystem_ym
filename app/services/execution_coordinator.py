from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.enums import ApprovalState, ExecutionFillStage, ExecutionMode, OrderLifecycleState, SubmitDecision
from app.db.models import OrderIntent, OrderSubmission, Plan
from app.repositories.execution import OrderIntentRepository, OrderSubmissionRepository, PlanRepository
from app.services.execution.approval import ExecutionPlanningService


@dataclass(slots=True)
class AdapterSubmitResult:
    state: OrderLifecycleState
    submit_status: str
    message: str
    exchange_order_id: str | None
    raw: dict[str, Any]
    attachments: dict[str, Any]
    fill_events: list[dict[str, Any]]
    acknowledged_at: datetime | None = None
    cancelled_at: datetime | None = None
    side: str = ""
    order_type: str = ""
    reduce_only: bool = False


class PaperExecutionAdapter:
    def _side(self, plan: Plan) -> str:
        return "BUY" if str(plan.direction).lower() == "long" else "SELL"

    def _order_type(self, plan: Plan) -> str:
        return "LIMIT" if str(plan.entry_model).upper() == "LIMIT" else "MARKET"

    def submit(
        self,
        *,
        intent: OrderIntent,
        plan: Plan,
        client_order_id: str,
        scenario: str | None = None,
    ) -> AdapterSubmitResult:
        now = datetime.now(timezone.utc)
        scenario_name = str(scenario or "fill").lower()
        exchange_order_id = f"paper_{uuid4().hex[:10]}"
        attachments = {
            "status": "reserved",
            "stop_price": float(plan.sl),
            "tp_targets": [
                {"label": "TP1", "price": float(plan.tp1)},
                {"label": "TP2", "price": float(plan.tp2)},
                {"label": "TP3", "price": float(plan.tp3)},
            ],
        }
        if scenario_name == "attach_failure":
            attachments["status"] = "failed"
            attachments["reason"] = "tp_sl_attach_failed"

        base = {
            "exchange_order_id": exchange_order_id,
            "client_order_id": client_order_id,
            "scenario": scenario_name,
            "symbol": plan.symbol,
        }
        fill_payload = {
            "source": "paper_adapter",
            "client_order_id": client_order_id,
            "exchange_order_id": exchange_order_id,
        }
        fill_events: list[dict[str, Any]] = []
        if scenario_name == "reject":
            return AdapterSubmitResult(
                state=OrderLifecycleState.REJECTED,
                submit_status="REJECTED",
                message="Paper adapter rejected the simulated order.",
                exchange_order_id=exchange_order_id,
                raw={**base, "status": "REJECTED"},
                attachments=attachments,
                fill_events=[],
                side=self._side(plan),
                order_type=self._order_type(plan),
            )
        if scenario_name in {"timeout", "cancel"}:
            return AdapterSubmitResult(
                state=OrderLifecycleState.CANCELLED,
                submit_status="TIMEOUT_CANCELLED" if scenario_name == "timeout" else "CANCELLED",
                message="Paper adapter cancelled the order after the requested scenario.",
                exchange_order_id=exchange_order_id,
                raw={**base, "status": "CANCELLED"},
                attachments=attachments,
                fill_events=[],
                acknowledged_at=now,
                cancelled_at=now,
                side=self._side(plan),
                order_type=self._order_type(plan),
            )
        if scenario_name == "partial_fill":
            fill_events.append(
                {
                    "fill_id": f"paper_fill_{uuid4().hex[:16]}",
                    "plan_id": plan.plan_id,
                    "symbol": plan.symbol,
                    "stage": ExecutionFillStage.ENTRY,
                    "fill_ts": now,
                    "price": float(plan.entry_price),
                    "qty": 0.5,
                    "fee": 0.0,
                    "payload": {**fill_payload, "partial": True},
                }
            )
            return AdapterSubmitResult(
                state=OrderLifecycleState.PARTIALLY_FILLED,
                submit_status="PARTIALLY_FILLED",
                message="Paper adapter simulated a partial fill.",
                exchange_order_id=exchange_order_id,
                raw={**base, "status": "PARTIALLY_FILLED"},
                attachments=attachments,
                fill_events=fill_events,
                acknowledged_at=now,
                side=self._side(plan),
                order_type=self._order_type(plan),
            )

        fill_events.append(
            {
                "fill_id": f"paper_fill_{uuid4().hex[:16]}",
                "plan_id": plan.plan_id,
                "symbol": plan.symbol,
                "stage": ExecutionFillStage.ENTRY,
                "fill_ts": now,
                "price": float(plan.entry_price),
                "qty": 1.0,
                "fee": 0.0,
                "payload": fill_payload,
            }
        )
        return AdapterSubmitResult(
            state=OrderLifecycleState.FILLED if scenario_name == "fill" else OrderLifecycleState.ACKNOWLEDGED,
            submit_status="FILLED" if scenario_name == "fill" else "ACKNOWLEDGED",
            message="Paper adapter accepted the order.",
            exchange_order_id=exchange_order_id,
            raw={**base, "status": "FILLED" if scenario_name == "fill" else "NEW"},
            attachments=attachments,
            fill_events=fill_events if scenario_name == "fill" else [],
            acknowledged_at=now,
            side=self._side(plan),
            order_type=self._order_type(plan),
        )


class ExecutionCoordinator:
    def __init__(
        self,
        *,
        plan_repo: PlanRepository,
        intent_repo: OrderIntentRepository,
        submission_repo: OrderSubmissionRepository,
        approval_loader: Callable[[str, ExecutionMode, bool], dict],
        fill_ingest: Callable[..., dict],
        live_submitter: Callable[..., dict],
        settings: Settings | None = None,
        paper_adapter: PaperExecutionAdapter | None = None,
    ):
        self.plan_repo = plan_repo
        self.intent_repo = intent_repo
        self.submission_repo = submission_repo
        self.approval_loader = approval_loader
        self.fill_ingest = fill_ingest
        self.live_submitter = live_submitter
        self.settings = settings or get_settings()
        self.paper_adapter = paper_adapter or PaperExecutionAdapter()

    @staticmethod
    def _client_order_id(intent_id: str) -> str:
        return f"intent-{intent_id[-16:]}"

    @staticmethod
    def _terminal_state(status: str) -> OrderLifecycleState:
        mapping = {
            "PARTIALLY_FILLED": OrderLifecycleState.PARTIALLY_FILLED,
            "FILLED": OrderLifecycleState.FILLED,
            "CANCELED": OrderLifecycleState.CANCELLED,
            "CANCELLED": OrderLifecycleState.CANCELLED,
            "REJECTED": OrderLifecycleState.REJECTED,
            "EXPIRED": OrderLifecycleState.CANCELLED,
        }
        return mapping.get(str(status or "").upper(), OrderLifecycleState.ACKNOWLEDGED)

    def _rejection_submission(
        self,
        *,
        intent: OrderIntent,
        plan: Plan,
        message: str,
        submit_status: str,
        client_order_id: str,
    ) -> OrderSubmission:
        row = OrderSubmission(
            submission_id=f"sub_{uuid4().hex[:20]}",
            intent_id=intent.intent_id,
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            client_order_id=client_order_id,
            exchange_order_id=None,
            state=OrderLifecycleState.REJECTED.value,
            submit_status=submit_status,
            message=message,
            adapter="none",
            execution_mode=intent.execution_mode,
            side="BUY" if str(plan.direction).lower() == "long" else "SELL",
            order_type="LIMIT" if str(plan.entry_model).upper() == "LIMIT" else "MARKET",
            requested_live=False,
            attachments={"session_guidance": dict(intent.session_guidance or {})},
            raw={
                "rejected": True,
                "submit_status": submit_status,
                "intent_snapshot": {"session_guidance": dict(intent.session_guidance or {})},
            },
        )
        self.submission_repo.add(row)
        return row

    def submit_intent(
        self,
        *,
        intent_id: str,
        live: bool = False,
        paper_scenario: str | None = None,
    ) -> tuple[OrderSubmission, list[dict[str, Any]], bool]:
        existing = self.submission_repo.latest_for_intent(intent_id)
        if existing is not None:
            return existing, list((existing.raw or {}).get("fill_results") or []), True

        intent = self.intent_repo.get(intent_id)
        if intent is None:
            raise ValueError("intent_not_found")
        plan = self.plan_repo.get(intent.plan_id)
        if plan is None:
            raise ValueError("plan_not_found")

        requested_mode = ExecutionPlanningService.coerce_execution_mode(intent.execution_mode)
        client_order_id = self._client_order_id(intent.intent_id)
        paper_lineage_override = bool(dict(intent.approval_snapshot or {}).get("paper_lineage_override_applied"))
        approval_bundle = self.approval_loader(
            plan.plan_id,
            requested_mode,
            paper_lineage_override=paper_lineage_override,
        )
        approval = dict(approval_bundle["approval"])
        approval_state = ApprovalState(str(approval.get("approval_state") or ApprovalState.BLOCKED.value))

        if SubmitDecision(str(intent.submit_decision)) != SubmitDecision.SUBMIT:
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Intent is not submit-ready and cannot be forwarded to an adapter.",
                submit_status="INTENT_NOT_SUBMITTABLE",
                client_order_id=client_order_id,
            )
            return row, [], False
        if approval_state != ApprovalState.APPROVED_AUTO:
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Approval state is no longer auto-approved at submit time.",
                submit_status="APPROVAL_NOT_AUTO",
                client_order_id=client_order_id,
            )
            return row, [], False
        if bool(self.settings.auto_trading_close_only) or bool((approval.get("operating_lock") or {}).get("active")):
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Close-only mode or an operating lock blocks new submits.",
                submit_status="SAFETY_BLOCKED",
                client_order_id=client_order_id,
            )
            return row, [], False

        fill_results: list[dict[str, Any]] = []
        if requested_mode == ExecutionMode.PAPER:
            if live:
                row = self._rejection_submission(
                    intent=intent,
                    plan=plan,
                    message="PAPER intents cannot request the live exchange path.",
                    submit_status="PAPER_CANNOT_REQUEST_LIVE",
                    client_order_id=client_order_id,
                )
                return row, [], False
            adapter_result = self.paper_adapter.submit(
                intent=intent,
                plan=plan,
                client_order_id=client_order_id,
                scenario=paper_scenario,
            )
            for item in adapter_result.fill_events:
                fill_results.append(
                    self.fill_ingest(
                        fill_id=item["fill_id"],
                        plan_id=item["plan_id"],
                        symbol=item["symbol"],
                        stage=item["stage"],
                        fill_ts=item["fill_ts"],
                        price=item["price"],
                        qty=item["qty"],
                        fee=item["fee"],
                        payload=item.get("payload") or {},
                    )
                )
            row = OrderSubmission(
                submission_id=f"sub_{uuid4().hex[:20]}",
                intent_id=intent.intent_id,
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                client_order_id=client_order_id,
                exchange_order_id=adapter_result.exchange_order_id,
                state=adapter_result.state.value,
                submit_status=adapter_result.submit_status,
                message=adapter_result.message,
                adapter="paper",
                execution_mode=requested_mode.value,
                side=adapter_result.side,
                order_type=adapter_result.order_type,
                reduce_only=adapter_result.reduce_only,
                requested_live=False,
                attachments={**adapter_result.attachments, "session_guidance": dict(intent.session_guidance or {})},
                raw={
                    **adapter_result.raw,
                    "fill_results": fill_results,
                    "intent_snapshot": {"session_guidance": dict(intent.session_guidance or {})},
                },
                submitted_at=datetime.now(timezone.utc),
                acknowledged_at=adapter_result.acknowledged_at,
                cancelled_at=adapter_result.cancelled_at,
            )
            self.submission_repo.add(row)
            return row, fill_results, False

        if requested_mode == ExecutionMode.SHADOW:
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Shadow-only intents are not routed to an execution adapter.",
                submit_status="SHADOW_ONLY",
                client_order_id=client_order_id,
            )
            return row, [], False
        if requested_mode != ExecutionMode.MICRO_LIVE:
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Binance live routing is currently limited to MICRO_LIVE intents.",
                submit_status="LIVE_MODE_NOT_SUPPORTED",
                client_order_id=client_order_id,
            )
            return row, [], False
        if not live:
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Live submit requires an explicit live=true request.",
                submit_status="LIVE_CONFIRMATION_REQUIRED",
                client_order_id=client_order_id,
            )
            return row, [], False
        if not bool(self.settings.binance_trade_live_enabled):
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Binance live submit is disabled in settings.",
                submit_status="LIVE_DISABLED",
                client_order_id=client_order_id,
            )
            return row, [], False

        live_result = self.live_submitter(
            symbol=plan.symbol,
            side="BUY" if str(plan.direction).lower() == "long" else "SELL",
            order_type="LIMIT" if str(plan.entry_model).upper() == "LIMIT" else "MARKET",
            quantity=max(0.001, float((intent.quality_snapshot or {}).get("recommended_risk_r", 0.0) or 0.01)),
            price=float(plan.entry_price) if str(plan.entry_model).upper() == "LIMIT" else None,
            time_in_force="GTC",
            reduce_only=False,
            client_order_id=client_order_id,
            plan_id=plan.plan_id,
            live=True,
            new_order_resp_type="RESULT",
        )
        status = str(live_result.get("status") or "NEW").upper()
        state = self._terminal_state(status)
        acknowledged_at = datetime.now(timezone.utc) if state in {
            OrderLifecycleState.ACKNOWLEDGED,
            OrderLifecycleState.PARTIALLY_FILLED,
            OrderLifecycleState.FILLED,
        } else None
        cancelled_at = datetime.now(timezone.utc) if state == OrderLifecycleState.CANCELLED else None
        row = OrderSubmission(
            submission_id=f"sub_{uuid4().hex[:20]}",
            intent_id=intent.intent_id,
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            client_order_id=str(live_result.get("client_order_id") or client_order_id),
            exchange_order_id=str(live_result.get("order_id")) if live_result.get("order_id") is not None else None,
            state=state.value,
            submit_status=status,
            message="Live submit forwarded to Binance adapter.",
            adapter="binance",
            execution_mode=requested_mode.value,
            side=str(live_result.get("side") or ""),
            order_type=str(live_result.get("order_type") or ""),
            reduce_only=bool(live_result.get("reduce_only")),
            requested_live=True,
            attachments={"status": "pending_attach"},
            raw=dict(live_result),
            submitted_at=datetime.now(timezone.utc),
            acknowledged_at=acknowledged_at,
            cancelled_at=cancelled_at,
        )
        self.submission_repo.add(row)
        return row, [], False
