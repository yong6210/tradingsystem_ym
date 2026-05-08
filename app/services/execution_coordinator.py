from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.enums import ApprovalState, ExecutionFillStage, ExecutionMode, OrderLifecycleState, SubmitDecision
from app.db.models import OrderIntent, OrderSubmission, Plan
from app.repositories.execution import OrderIntentRepository, OrderSubmissionRepository, PlanRepository
from app.services.lane_tracker import get_execution_lane_tracker
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
        live_symbol_rules_loader: Callable[[str], dict[str, Any] | None] | None = None,
        settings: Settings | None = None,
        paper_adapter: PaperExecutionAdapter | None = None,
    ):
        self.plan_repo = plan_repo
        self.intent_repo = intent_repo
        self.submission_repo = submission_repo
        self.approval_loader = approval_loader
        self.fill_ingest = fill_ingest
        self.live_submitter = live_submitter
        self.live_symbol_rules_loader = live_symbol_rules_loader
        self.settings = settings or get_settings()
        self.paper_adapter = paper_adapter or PaperExecutionAdapter()
        self._live_symbol_rules_cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _client_order_id(intent_id: str) -> str:
        return f"intent-{intent_id[-16:]}"

    @staticmethod
    def _submission_blocks_plan_reentry(row: OrderSubmission | None) -> bool:
        if row is None:
            return False
        if str(row.adapter or "").lower() == "none":
            return False
        return str(row.state or "") in {
            OrderLifecycleState.CREATED.value,
            OrderLifecycleState.SUBMITTED.value,
            OrderLifecycleState.ACKNOWLEDGED.value,
            OrderLifecycleState.PARTIALLY_FILLED.value,
            OrderLifecycleState.FILLED.value,
        }

    @staticmethod
    def _intent_is_transition_edge_variant(intent: OrderIntent) -> bool:
        payload = dict(intent.payload or {})
        executable_plan = dict(payload.get("executable_plan") or {})
        if bool(executable_plan.get("transition_edge_variant_applied")):
            return True
        return bool(dict(executable_plan.get("transition_edge_variant") or {}))

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
        requested_live: bool = False,
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
            requested_live=bool(requested_live),
            attachments={"session_guidance": dict(intent.session_guidance or {})},
            raw={
                "rejected": True,
                "submit_status": submit_status,
                "intent_snapshot": {"session_guidance": dict(intent.session_guidance or {})},
            },
        )
        self.submission_repo.add(row)
        return row

    @staticmethod
    def _round_down_to_step(value: float, *, step: float) -> float:
        normalized_step = max(float(step or 0.0), 1e-9)
        value_dec = Decimal(str(max(float(value or 0.0), 0.0)))
        step_dec = Decimal(str(normalized_step))
        rounded = (value_dec / step_dec).to_integral_value(rounding=ROUND_DOWN) * step_dec
        return float(rounded)

    @staticmethod
    def _round_up_to_step(value: float, *, step: float) -> float:
        normalized_step = max(float(step or 0.0), 1e-9)
        value_dec = Decimal(str(max(float(value or 0.0), 0.0)))
        step_dec = Decimal(str(normalized_step))
        rounded = (value_dec / step_dec).to_integral_value(rounding=ROUND_UP) * step_dec
        return float(rounded)

    def _live_symbol_rules(self, symbol: str) -> tuple[dict[str, Any] | None, str | None]:
        normalized_symbol = str(symbol or "").upper()
        symbol_rules = self._live_symbol_rules_cache.get(normalized_symbol)
        if symbol_rules is not None:
            return symbol_rules, None
        if self.live_symbol_rules_loader is None:
            return None, None
        try:
            loaded = self.live_symbol_rules_loader(normalized_symbol) or {}
            symbol_rules = dict(loaded)
            if symbol_rules:
                self._live_symbol_rules_cache[normalized_symbol] = dict(symbol_rules)
            return symbol_rules or None, None
        except Exception as exc:  # pragma: no cover - defensive fallback
            return None, str(exc)

    def _normalize_live_limit_price(
        self,
        *,
        symbol: str,
        side: str,
        requested_price: float | None,
    ) -> tuple[float | None, dict[str, Any]]:
        if requested_price is None:
            return None, {}

        details: dict[str, Any] = {"requested_limit_price": round(float(requested_price), 8)}
        symbol_rules, symbol_rules_error = self._live_symbol_rules(symbol)
        if symbol_rules_error:
            details["price_rules_loader_error"] = symbol_rules_error
        tick_size = float((symbol_rules or {}).get("tick_size") or 0.0)
        if tick_size <= 0.0:
            details["price_rules_source"] = str((symbol_rules or {}).get("source") or "settings_passthrough")
            details["normalized_limit_price"] = round(float(requested_price), 8)
            return float(requested_price), details

        normalized_side = str(side or "").upper()
        if normalized_side == "SELL":
            normalized_price = self._round_up_to_step(float(requested_price), step=tick_size)
        else:
            normalized_price = self._round_down_to_step(float(requested_price), step=tick_size)
        details.update(
            {
                "tick_size": round(tick_size, 8),
                "price_rules_source": str((symbol_rules or {}).get("source") or "binance_exchange_info"),
                "normalized_limit_price": round(float(normalized_price), 8),
            }
        )
        return float(normalized_price), details

    @staticmethod
    def _maybe_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _live_submit_fill_payload(
        self,
        *,
        intent: OrderIntent,
        plan: Plan,
        live_result: dict[str, Any],
        client_order_id: str,
    ) -> tuple[str, float, float, dict[str, Any]] | None:
        status = str(live_result.get("status") or "").upper()
        if status not in {"PARTIALLY_FILLED", "FILLED"}:
            return None

        raw = dict(live_result.get("raw") or {})
        executed_qty = (
            self._maybe_float(live_result.get("executed_qty"))
            or self._maybe_float(raw.get("executedQty"))
            or self._maybe_float(raw.get("executed_qty"))
        )
        if executed_qty is None or executed_qty <= 0.0:
            return None

        fill_price = (
            self._maybe_float(live_result.get("avg_price"))
            or self._maybe_float(raw.get("avgPrice"))
            or self._maybe_float(raw.get("avg_price"))
            or self._maybe_float(live_result.get("price"))
            or self._maybe_float(raw.get("price"))
        )
        if fill_price is None or fill_price <= 0.0:
            return None

        exchange_order_id = str(
            live_result.get("order_id")
            or raw.get("orderId")
            or live_result.get("exchange_order_id")
            or ""
        ).strip()
        fill_anchor = exchange_order_id or client_order_id or str(plan.plan_id or "")
        fill_id = f"binance_submit_{fill_anchor}_{status.lower()}"
        fill_payload = {
            "source": "binance_submit_response",
            "client_order_id": str(live_result.get("client_order_id") or client_order_id),
            "exchange_order_id": exchange_order_id,
            "submit_status": status,
            "side": str(live_result.get("side") or ""),
            "order_type": str(live_result.get("order_type") or ""),
            "reduce_only": bool(live_result.get("reduce_only")),
            "notes": {"submit_path": "execution_coordinator_live_submit"},
        }
        return fill_id, float(fill_price), float(executed_qty), fill_payload

    def _live_order_sizing(self, *, intent: OrderIntent, plan: Plan) -> tuple[float | None, dict[str, Any], str | None]:
        payload = dict(intent.payload or {})
        executable_plan = dict(payload.get("executable_plan") or {})
        quality_snapshot = dict(intent.quality_snapshot or {})
        sizing_mode = str(getattr(self.settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R") or "NOTIONAL_PER_R").strip().upper()
        reference_price = float(
            executable_plan.get("entry_limit_price")
            or executable_plan.get("entry_trigger_price")
            or getattr(plan, "entry_price", 0.0)
            or 0.0
        )
        stop_price = float(executable_plan.get("stop_price") or getattr(plan, "sl", 0.0) or 0.0)
        default_step = float(getattr(self.settings, "binance_live_quantity_step", 0.001) or 0.001)
        default_min_quantity = float(getattr(self.settings, "binance_live_min_quantity", default_step) or default_step)
        step = default_step
        min_quantity = default_min_quantity
        symbol_rules_source = "settings_default"
        symbol_rules_error: str | None = None
        symbol_rules, symbol_rules_error = self._live_symbol_rules(str(plan.symbol or "").upper())
        if symbol_rules:
            step = float(symbol_rules.get("quantity_step") or default_step)
            min_quantity = float(symbol_rules.get("min_quantity") or default_min_quantity or step)
            symbol_rules_source = str(symbol_rules.get("source") or "binance_exchange_info")

        sizing_details = {
            "sizing_mode": sizing_mode,
            "recommended_risk_r": float(quality_snapshot.get("recommended_risk_r", 0.0) or 0.0),
            "reference_price": round(reference_price, 8),
            "stop_price": round(stop_price, 8),
            "quantity_step": round(step, 8),
            "min_quantity": round(min_quantity, 8),
            "symbol_rules_source": symbol_rules_source,
        }
        if symbol_rules_error:
            sizing_details["symbol_rules_loader_error"] = symbol_rules_error
        if symbol_rules:
            tick_size = symbol_rules.get("tick_size")
            if tick_size not in {None, ""}:
                sizing_details["tick_size"] = round(float(tick_size), 8)
        if reference_price <= 0.0:
            return None, sizing_details, "Live submit requires a positive reference price."
        max_position_notional = 0.0
        if sizing_mode == "RISK_PCT":
            account_equity_usdt = float(getattr(self.settings, "auto_trading_live_account_equity_usdt", 0.0) or 0.0)
            risk_per_trade_pct = float(getattr(self.settings, "auto_trading_live_risk_per_trade_pct", 0.0) or 0.0)
            usable_margin_fraction = float(getattr(self.settings, "auto_trading_live_usable_margin_fraction", 0.0) or 0.0)
            leverage_cap = float(getattr(self.settings, "auto_trading_live_leverage_cap", 0.0) or 0.0)
            stop_pct = abs(reference_price - stop_price) / reference_price if reference_price > 0.0 else 0.0
            target_risk_usdt = account_equity_usdt * risk_per_trade_pct
            usable_margin_usdt = account_equity_usdt * usable_margin_fraction
            target_notional = target_risk_usdt / stop_pct if stop_pct > 0.0 else 0.0
            leverage_cap_notional = max(usable_margin_usdt, 0.0) * max(leverage_cap, 0.0)
            max_position_notional = min(target_notional, leverage_cap_notional) if leverage_cap_notional > 0.0 else 0.0
            required_leverage = target_notional / usable_margin_usdt if usable_margin_usdt > 0.0 else 0.0
            actual_risk_usdt = max_position_notional * stop_pct
            actual_risk_pct = actual_risk_usdt / account_equity_usdt if account_equity_usdt > 0.0 else 0.0
            leverage_capped = max_position_notional + 1e-12 < target_notional

            sizing_details.update(
                {
                    "account_equity_usdt": round(account_equity_usdt, 4),
                    "risk_per_trade_pct": round(risk_per_trade_pct, 6),
                    "usable_margin_fraction": round(usable_margin_fraction, 6),
                    "usable_margin_usdt": round(usable_margin_usdt, 4),
                    "stop_pct": round(stop_pct, 8),
                    "target_risk_usdt": round(target_risk_usdt, 4),
                    "target_notional": round(target_notional, 4),
                    "required_leverage": round(required_leverage, 4),
                    "leverage_cap": round(leverage_cap, 4),
                    "leverage_cap_notional": round(leverage_cap_notional, 4),
                    "max_position_notional": round(max_position_notional, 4),
                    "actual_risk_usdt": round(actual_risk_usdt, 4),
                    "actual_risk_pct": round(actual_risk_pct, 6),
                    "leverage_capped": bool(leverage_capped),
                    "sizing_status": "capped_by_leverage" if leverage_capped else "target_risk_matched",
                }
            )
            if account_equity_usdt <= 0.0:
                return None, sizing_details, "Live risk sizing requires AUTO_TRADING_LIVE_ACCOUNT_EQUITY_USDT > 0."
            if risk_per_trade_pct <= 0.0:
                return None, sizing_details, "Live risk sizing requires AUTO_TRADING_LIVE_RISK_PER_TRADE_PCT > 0."
            if usable_margin_fraction <= 0.0:
                return None, sizing_details, "Live risk sizing requires AUTO_TRADING_LIVE_USABLE_MARGIN_FRACTION > 0."
            if leverage_cap <= 0.0:
                return None, sizing_details, "Live risk sizing requires AUTO_TRADING_LIVE_LEVERAGE_CAP > 0."
            if stop_pct <= 0.0:
                return None, sizing_details, "Live risk sizing requires a positive stop distance."
        else:
            max_position_notional = float(
                executable_plan.get(
                    "max_position_notional",
                    quality_snapshot.get("max_position_notional", 0.0),
                )
                or 0.0
            )
            if max_position_notional <= 0.0:
                max_position_notional = round(
                    max(float(quality_snapshot.get("recommended_risk_r", 0.0) or 0.0), 0.0)
                    * float(self.settings.auto_trading_notional_per_r),
                    4,
                )
            sizing_details.update(
                {
                    "max_position_notional": round(max_position_notional, 4),
                    "sizing_status": "notional_per_r",
                }
            )

        if max_position_notional <= 0.0:
            return None, sizing_details, "Live submit requires a positive max_position_notional."

        raw_quantity = max_position_notional / reference_price
        normalized_quantity = self._round_down_to_step(raw_quantity, step=step)
        sizing_details["raw_quantity"] = round(raw_quantity, 8)
        sizing_details["normalized_quantity"] = round(normalized_quantity, 8)

        if normalized_quantity + 1e-12 < min_quantity:
            return (
                None,
                sizing_details,
                (
                    "Computed live quantity "
                    f"{normalized_quantity:.6f} is below the configured minimum {min_quantity:.6f}; "
                    f"increase AUTO_TRADING_NOTIONAL_PER_R or lower the minimum quantity for this symbol."
                ),
            )
        return normalized_quantity, sizing_details, None

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
        for existing_submission in self.submission_repo.list_for_plan(plan.plan_id, limit=20):
            if existing_submission.intent_id == intent.intent_id:
                continue
            if not self._submission_blocks_plan_reentry(existing_submission):
                continue
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message=(
                    f"Plan already has routed submission {existing_submission.submission_id} "
                    f"in state {existing_submission.state}."
                ),
                submit_status="PLAN_REENTRY_BLOCKED",
                client_order_id=self._client_order_id(intent.intent_id),
                requested_live=live,
            )
            return row, [], False

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
        effective_mode = ExecutionPlanningService.coerce_execution_mode(
            approval.get("allowed_execution_mode"),
            default=requested_mode,
        )

        if SubmitDecision(str(intent.submit_decision)) != SubmitDecision.SUBMIT:
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Intent is not submit-ready and cannot be forwarded to an adapter.",
                submit_status="INTENT_NOT_SUBMITTABLE",
                client_order_id=client_order_id,
                requested_live=live,
            )
            return row, [], False
        if approval_state != ApprovalState.APPROVED_AUTO:
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Approval state is no longer auto-approved at submit time.",
                submit_status="APPROVAL_NOT_AUTO",
                client_order_id=client_order_id,
                requested_live=live,
            )
            return row, [], False
        if bool(self.settings.auto_trading_close_only) or bool((approval.get("operating_lock") or {}).get("active")):
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Close-only mode or an operating lock blocks new submits.",
                submit_status="SAFETY_BLOCKED",
                client_order_id=client_order_id,
                requested_live=live,
            )
            return row, [], False

        fill_results: list[dict[str, Any]] = []
        if effective_mode == ExecutionMode.PAPER:
            if live:
                row = self._rejection_submission(
                    intent=intent,
                    plan=plan,
                    message="PAPER intents cannot request the live exchange path.",
                    submit_status="PAPER_CANNOT_REQUEST_LIVE",
                    client_order_id=client_order_id,
                    requested_live=live,
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
                execution_mode=effective_mode.value,
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
            tracker = get_execution_lane_tracker(window=int(self.settings.transition_edge_variant_lane_tracker_window))
            tracker.record_submitted(is_variant=self._intent_is_transition_edge_variant(intent))
            return row, fill_results, False

        if effective_mode == ExecutionMode.SHADOW:
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Shadow-only intents are not routed to an execution adapter.",
                submit_status="SHADOW_ONLY",
                client_order_id=client_order_id,
                requested_live=live,
            )
            return row, [], False
        if effective_mode != ExecutionMode.MICRO_LIVE:
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Binance live routing is currently limited to MICRO_LIVE intents.",
                submit_status="LIVE_MODE_NOT_SUPPORTED",
                client_order_id=client_order_id,
                requested_live=live,
            )
            return row, [], False
        if not live:
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Live submit requires an explicit live=true request.",
                submit_status="LIVE_CONFIRMATION_REQUIRED",
                client_order_id=client_order_id,
                requested_live=live,
            )
            return row, [], False
        if not bool(self.settings.binance_trade_live_enabled):
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Binance live submit is disabled in settings.",
                submit_status="LIVE_DISABLED",
                client_order_id=client_order_id,
                requested_live=live,
            )
            return row, [], False

        live_quantity, live_sizing, sizing_error = self._live_order_sizing(intent=intent, plan=plan)
        if sizing_error is not None or live_quantity is None:
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message=sizing_error or "Live submit sizing failed.",
                submit_status="LIVE_SIZING_INVALID",
                client_order_id=client_order_id,
                requested_live=live,
            )
            row.attachments = {
                **dict(row.attachments or {}),
                "live_order_sizing": live_sizing,
                "session_guidance": dict(intent.session_guidance or {}),
            }
            row.raw = {
                **dict(row.raw or {}),
                "live_order_sizing": live_sizing,
            }
            return row, [], False

        live_side = "BUY" if str(plan.direction).lower() == "long" else "SELL"
        live_order_type = "LIMIT" if str(plan.entry_model).upper() == "LIMIT" else "MARKET"
        live_limit_price = float(plan.entry_price) if live_order_type == "LIMIT" else None
        normalized_live_price, live_price_details = self._normalize_live_limit_price(
            symbol=plan.symbol,
            side=live_side,
            requested_price=live_limit_price,
        )
        live_sizing = {
            **dict(live_sizing or {}),
            **({"live_limit_price": live_price_details} if live_price_details else {}),
        }
        if live_order_type == "LIMIT" and (normalized_live_price is None or normalized_live_price <= 0.0):
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Live submit limit price normalization failed.",
                submit_status="LIVE_PRICE_INVALID",
                client_order_id=client_order_id,
                requested_live=live,
            )
            row.attachments = {
                **dict(row.attachments or {}),
                "live_order_sizing": live_sizing,
                "session_guidance": dict(intent.session_guidance or {}),
            }
            row.raw = {
                **dict(row.raw or {}),
                "live_order_sizing": live_sizing,
            }
            return row, [], False

        live_result = self.live_submitter(
            symbol=plan.symbol,
            side=live_side,
            order_type=live_order_type,
            quantity=live_quantity,
            price=normalized_live_price if live_order_type == "LIMIT" else None,
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
            execution_mode=effective_mode.value,
            side=str(live_result.get("side") or ""),
            order_type=str(live_result.get("order_type") or ""),
            reduce_only=bool(live_result.get("reduce_only")),
            requested_live=True,
            attachments={
                "status": "pending_attach",
                "live_order_sizing": live_sizing,
                "session_guidance": dict(intent.session_guidance or {}),
            },
            raw={
                **dict(live_result),
                "live_order_sizing": live_sizing,
                "intent_snapshot": {"session_guidance": dict(intent.session_guidance or {})},
            },
            submitted_at=datetime.now(timezone.utc),
            acknowledged_at=acknowledged_at,
            cancelled_at=cancelled_at,
        )
        self.submission_repo.add(row)
        live_fill = self._live_submit_fill_payload(
            intent=intent,
            plan=plan,
            live_result=live_result,
            client_order_id=client_order_id,
        )
        if live_fill is not None:
            fill_id, fill_price, fill_qty, fill_payload = live_fill
            fill_results.append(
                self.fill_ingest(
                    fill_id=fill_id,
                    plan_id=plan.plan_id,
                    symbol=plan.symbol,
                    stage=ExecutionFillStage.ENTRY,
                    fill_ts=datetime.now(timezone.utc),
                    price=fill_price,
                    qty=fill_qty,
                    fee=0.0,
                    payload=fill_payload,
                )
            )
            row.attachments = {
                **dict(row.attachments or {}),
                "immediate_fill_ingested": True,
            }
            row.raw = {
                **dict(row.raw or {}),
                "fill_results": fill_results,
            }
        tracker = get_execution_lane_tracker(window=int(self.settings.transition_edge_variant_lane_tracker_window))
        tracker.record_submitted(is_variant=self._intent_is_transition_edge_variant(intent))
        return row, fill_results, False
