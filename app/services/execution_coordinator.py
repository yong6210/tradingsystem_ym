from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from datetime import datetime, timezone
from math import isfinite
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
        live_liquidity_loader: Callable[..., dict[str, Any] | None] | None = None,
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
        self.live_liquidity_loader = live_liquidity_loader
        self.settings = settings or get_settings()
        self.paper_adapter = paper_adapter or PaperExecutionAdapter()
        self._live_symbol_rules_cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _client_order_id(intent_id: str) -> str:
        return f"intent-{intent_id[-16:]}"

    @staticmethod
    def _safe_dict(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

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
        payload = ExecutionCoordinator._safe_dict(intent.payload)
        executable_plan = ExecutionCoordinator._safe_dict(payload.get("executable_plan"))
        if bool(executable_plan.get("transition_edge_variant_applied")):
            return True
        return bool(ExecutionCoordinator._safe_dict(executable_plan.get("transition_edge_variant")))

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
        session_guidance = self._safe_dict(intent.session_guidance)
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
            attachments={"session_guidance": session_guidance},
            raw={
                "rejected": True,
                "submit_status": submit_status,
                "intent_snapshot": {"session_guidance": session_guidance},
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
            loaded = self.live_symbol_rules_loader(normalized_symbol)
            symbol_rules = self._safe_dict(loaded)
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
        tick_size = self._float_or((symbol_rules or {}).get("tick_size"), 0.0)
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
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if isfinite(parsed) else None

    @classmethod
    def _float_or(cls, value: Any, default: float = 0.0) -> float:
        parsed = cls._maybe_float(value)
        return float(default) if parsed is None else parsed

    @classmethod
    def _int_or(cls, value: Any, default: int = 0) -> int:
        parsed = cls._maybe_float(value)
        return int(default) if parsed is None else int(parsed)

    def _partial_submit_enabled(self) -> bool:
        return bool(getattr(self.settings, "auto_trading_live_liquidity_gate_partial_submit_enabled", False))

    def _lane_tracker(self):
        return get_execution_lane_tracker(
            window=max(
                1,
                self._int_or(getattr(self.settings, "transition_edge_variant_lane_tracker_window", 1), 1),
            )
        )

    def _min_tranche_notional(self) -> float:
        return max(
            0.0,
            self._float_or(getattr(self.settings, "auto_trading_live_liquidity_gate_min_tranche_notional_usdt", 0.0)),
        )

    @staticmethod
    def _live_tranche_from_submission(row: OrderSubmission | None) -> dict[str, Any]:
        if row is None:
            return {}
        attachments = ExecutionCoordinator._safe_dict(getattr(row, "attachments", None))
        raw = ExecutionCoordinator._safe_dict(getattr(row, "raw", None))
        tranche = ExecutionCoordinator._safe_dict(attachments.get("live_tranche") or raw.get("live_tranche"))
        return tranche

    def _intent_tranche_continuation(self, intent: OrderIntent) -> dict[str, Any]:
        dedupe = self._safe_dict(intent.dedupe_result)
        if str(dedupe.get("status") or "") != "tranche_continuation_available":
            return {}
        return self._safe_dict(dedupe.get("tranche_continuation"))

    def _apply_tranche_remaining_cap(
        self,
        *,
        intent: OrderIntent,
        max_position_notional: float,
        sizing_details: dict[str, Any],
    ) -> float:
        continuation = self._intent_tranche_continuation(intent)
        if not continuation or not self._partial_submit_enabled():
            return max_position_notional
        remaining_notional = self._maybe_float(continuation.get("remaining_notional"))
        if remaining_notional is None or remaining_notional <= 0.0:
            return max_position_notional

        capped_notional = min(float(max_position_notional), float(remaining_notional))
        sizing_details["liquidity_tranche_continuation"] = {
            "enabled": True,
            "parent_intent_id": str(continuation.get("parent_intent_id") or ""),
            "parent_submission_id": str(continuation.get("parent_submission_id") or ""),
            "parent_plan_id": str(continuation.get("parent_plan_id") or ""),
            "target_notional": round(self._float_or(continuation.get("target_notional"), max_position_notional), 4),
            "remaining_notional_before": round(float(remaining_notional), 4),
            "next_tranche_index": max(1, self._int_or(continuation.get("next_tranche_index"), 1)),
            "max_tranches": max(0, self._int_or(continuation.get("max_tranches"), 0)),
            "capped_max_position_notional": round(capped_notional, 4),
        }
        return capped_notional

    def _partial_tranche_order(
        self,
        *,
        intent: OrderIntent,
        plan: Plan,
        live_quantity: float,
        live_sizing: dict[str, Any],
        liquidity_gate: dict[str, Any],
        reference_price: float,
    ) -> tuple[float | None, dict[str, Any], str | None]:
        if not self._partial_submit_enabled():
            return None, {}, "partial_submit_disabled"
        target_notional = max(self._float_or(live_sizing.get("max_position_notional")), 0.0)
        if target_notional <= 0.0:
            target_notional = max(self._float_or(live_quantity), 0.0) * max(self._float_or(reference_price), 0.0)
        if target_notional <= 0.0 or reference_price <= 0.0:
            return None, {}, "partial_submit_invalid_target_notional"

        allowed_notional = self._maybe_float(liquidity_gate.get("allowed_notional"))
        if allowed_notional is None:
            allowed_notional = self._maybe_float(self._safe_dict(liquidity_gate.get("derived")).get("allowed_notional"))
        if allowed_notional is None or allowed_notional <= 0.0:
            return None, {}, "partial_submit_allowed_notional_unavailable"

        submitted_target_notional = min(float(allowed_notional), target_notional)
        min_tranche_notional = self._min_tranche_notional()
        if submitted_target_notional < min_tranche_notional:
            return None, {}, "partial_submit_allowed_notional_below_minimum"

        step = max(
            self._float_or(live_sizing.get("quantity_step"), self._float_or(getattr(self.settings, "binance_live_quantity_step", 0.001), 0.001)),
            1e-9,
        )
        min_quantity = max(
            self._float_or(live_sizing.get("min_quantity"), self._float_or(getattr(self.settings, "binance_live_min_quantity", step), step)),
            step,
        )
        partial_quantity = self._round_down_to_step(submitted_target_notional / reference_price, step=step)
        if partial_quantity + 1e-12 < min_quantity:
            return None, {}, "partial_submit_quantity_below_minimum"

        submitted_notional = partial_quantity * reference_price
        if submitted_notional < min_tranche_notional:
            return None, {}, "partial_submit_rounded_notional_below_minimum"

        continuation = self._intent_tranche_continuation(intent)
        remaining_before = self._maybe_float(continuation.get("remaining_notional")) if continuation else None
        if remaining_before is None or remaining_before <= 0.0:
            remaining_before = target_notional
        total_target_notional = self._maybe_float(continuation.get("target_notional")) if continuation else None
        if total_target_notional is None or total_target_notional <= 0.0:
            total_target_notional = target_notional

        tranche_index = max(1, self._int_or((continuation or {}).get("next_tranche_index"), 1))
        max_tranches = max(1, self._int_or(getattr(self.settings, "auto_trading_live_liquidity_gate_max_tranches", 1), 1))
        remaining_after = max(0.0, float(remaining_before) - submitted_notional)
        additive_allowed = remaining_after >= min_tranche_notional and tranche_index < max_tranches
        cluster_id = str(self._safe_dict(intent.dedupe_result).get("cluster_id") or "")
        live_tranche = {
            "enabled": True,
            "reason": "liquidity_split_partial_submit",
            "parent_intent_id": str((continuation or {}).get("parent_intent_id") or intent.intent_id),
            "parent_submission_id": str((continuation or {}).get("parent_submission_id") or ""),
            "parent_plan_id": str((continuation or {}).get("parent_plan_id") or plan.plan_id),
            "thesis_cluster_id": cluster_id,
            "tranche_index": tranche_index,
            "max_tranches": max_tranches,
            "target_notional": round(float(total_target_notional), 4),
            "remaining_notional_before": round(float(remaining_before), 4),
            "submitted_notional": round(submitted_notional, 4),
            "remaining_notional": round(remaining_after, 4),
            "min_tranche_notional": round(min_tranche_notional, 4),
            "additive_allowed": bool(additive_allowed),
            "next_tranche_index": tranche_index + 1 if additive_allowed else tranche_index,
            "reason_codes": list(liquidity_gate.get("reason_codes") or []),
        }
        adjusted_sizing = {
            **self._safe_dict(live_sizing),
            "liquidity_gate_decision": "SPLIT_PARTIAL_SUBMIT",
            "original_normalized_quantity": round(float(live_quantity or 0.0), 8),
            "original_max_position_notional": round(float(target_notional), 4),
            "normalized_quantity": round(float(partial_quantity), 8),
            "max_position_notional": round(submitted_notional, 4),
            "live_tranche": live_tranche,
        }
        return partial_quantity, adjusted_sizing, None

    def _live_liquidity_gate(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None,
        reference_price: float,
    ) -> dict[str, Any]:
        if not bool(getattr(self.settings, "auto_trading_live_liquidity_gate_enabled", False)):
            return {"enabled": False, "decision": "PASS", "reason_codes": []}

        thresholds = {
            "min_depth_usdt": max(
                0.0,
                self._float_or(getattr(self.settings, "auto_trading_live_liquidity_gate_min_depth_usdt", 0.0)),
            ),
            "max_depth_participation": max(
                0.0,
                self._float_or(getattr(self.settings, "auto_trading_live_liquidity_gate_max_depth_participation", 0.0)),
            ),
            "max_1m_volume_participation": max(
                0.0,
                self._float_or(getattr(self.settings, "auto_trading_live_liquidity_gate_max_1m_volume_participation", 0.0)),
            ),
            "max_5m_volume_participation": max(
                0.0,
                self._float_or(getattr(self.settings, "auto_trading_live_liquidity_gate_max_5m_volume_participation", 0.0)),
            ),
            "max_spread_bps": max(
                0.0,
                self._float_or(getattr(self.settings, "auto_trading_live_liquidity_gate_max_spread_bps", 0.0)),
            ),
            "max_market_slippage_bps": max(
                0.0,
                self._float_or(getattr(self.settings, "auto_trading_live_liquidity_gate_max_market_slippage_bps", 0.0)),
            ),
        }
        fail_closed = bool(getattr(self.settings, "auto_trading_live_liquidity_gate_fail_closed", True))
        order_notional = max(float(quantity or 0.0), 0.0) * max(float(price or reference_price or 0.0), 0.0)

        if self.live_liquidity_loader is None:
            decision = "BLOCK" if fail_closed else "PASS"
            return {
                "enabled": True,
                "decision": decision,
                "reason_codes": ["liquidity_loader_missing"],
                "message": "Live liquidity gate has no market-data loader.",
                "thresholds": thresholds,
                "order_notional": round(order_notional, 4),
            }

        try:
            snapshot = self.live_liquidity_loader(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                reference_price=reference_price,
            )
        except Exception as exc:  # pragma: no cover - defensive live-submit guard
            decision = "BLOCK" if fail_closed else "PASS"
            return {
                "enabled": True,
                "decision": decision,
                "reason_codes": ["liquidity_snapshot_error"],
                "message": f"Live liquidity snapshot failed: {exc}",
                "thresholds": thresholds,
                "order_notional": round(order_notional, 4),
            }

        snapshot_payload = self._safe_dict(snapshot)
        if not snapshot_payload:
            decision = "BLOCK" if fail_closed else "PASS"
            return {
                "enabled": True,
                "decision": decision,
                "reason_codes": ["liquidity_snapshot_unavailable"],
                "message": "Live liquidity snapshot was unavailable.",
                "thresholds": thresholds,
                "order_notional": round(order_notional, 4),
            }

        order_notional = self._maybe_float(snapshot_payload.get("order_notional")) or order_notional
        depth_notional = self._maybe_float(snapshot_payload.get("opposite_depth_notional"))
        spread_bps = self._maybe_float(snapshot_payload.get("spread_bps"))
        market_slippage_bps = self._maybe_float(snapshot_payload.get("market_slippage_bps"))
        volume_1m = self._maybe_float(snapshot_payload.get("recent_1m_quote_volume"))
        volume_5m = self._maybe_float(snapshot_payload.get("recent_5m_quote_volume"))

        block_codes: list[str] = []
        split_codes: list[str] = []
        derived: dict[str, Any] = {"order_notional": round(order_notional, 4)}
        notional_caps: list[dict[str, Any]] = []

        if depth_notional is None or depth_notional <= 0.0:
            if fail_closed:
                block_codes.append("orderbook_depth_unavailable")
        else:
            depth_participation = order_notional / depth_notional if depth_notional > 0.0 else 0.0
            derived["depth_participation"] = round(depth_participation, 6)
            if thresholds["min_depth_usdt"] > 0.0 and depth_notional < thresholds["min_depth_usdt"]:
                block_codes.append("visible_depth_below_floor")
            if (
                thresholds["max_depth_participation"] > 0.0
                and depth_participation > thresholds["max_depth_participation"]
            ):
                split_codes.append("depth_participation_too_high")
                notional_caps.append(
                    {
                        "source": "depth_participation",
                        "allowed_notional": depth_notional * thresholds["max_depth_participation"],
                    }
                )

        if spread_bps is None:
            if fail_closed:
                block_codes.append("spread_unavailable")
        elif thresholds["max_spread_bps"] > 0.0 and spread_bps > thresholds["max_spread_bps"]:
            block_codes.append("spread_too_wide")

        if (
            market_slippage_bps is not None
            and thresholds["max_market_slippage_bps"] > 0.0
            and market_slippage_bps > thresholds["max_market_slippage_bps"]
        ):
            split_codes.append("market_slippage_too_high")

        if volume_1m is not None and volume_1m > 0.0:
            participation_1m = order_notional / volume_1m
            derived["one_minute_volume_participation"] = round(participation_1m, 6)
            if (
                thresholds["max_1m_volume_participation"] > 0.0
                and participation_1m > thresholds["max_1m_volume_participation"]
            ):
                split_codes.append("one_minute_participation_too_high")
                notional_caps.append(
                    {
                        "source": "one_minute_volume_participation",
                        "allowed_notional": volume_1m * thresholds["max_1m_volume_participation"],
                    }
                )
        elif fail_closed:
            block_codes.append("one_minute_volume_unavailable")

        if volume_5m is not None and volume_5m > 0.0:
            participation_5m = order_notional / volume_5m
            derived["five_minute_volume_participation"] = round(participation_5m, 6)
            if (
                thresholds["max_5m_volume_participation"] > 0.0
                and participation_5m > thresholds["max_5m_volume_participation"]
            ):
                split_codes.append("five_minute_participation_too_high")
                notional_caps.append(
                    {
                        "source": "five_minute_volume_participation",
                        "allowed_notional": volume_5m * thresholds["max_5m_volume_participation"],
                    }
                )
        elif fail_closed:
            block_codes.append("five_minute_volume_unavailable")

        valid_caps = []
        for item in notional_caps:
            allowed_cap = self._maybe_float(item.get("allowed_notional"))
            if allowed_cap is None or allowed_cap <= 0.0:
                continue
            valid_caps.append(
                {
                    "source": str(item.get("source") or ""),
                    "allowed_notional": round(allowed_cap, 4),
                }
            )
        allowed_notional = min((float(item["allowed_notional"]) for item in valid_caps), default=0.0)
        if valid_caps:
            derived["notional_caps"] = valid_caps
            derived["allowed_notional"] = round(min(order_notional, allowed_notional), 4)

        if block_codes:
            decision = "BLOCK"
            reason_codes = block_codes + split_codes
            message = "Live order blocked by liquidity gate."
        elif split_codes:
            decision = "SPLIT_REQUIRED"
            reason_codes = split_codes
            message = "Live order exceeds liquidity participation limits; split or reduce size."
        else:
            decision = "PASS"
            reason_codes = []
            message = "Live liquidity gate passed."

        return {
            "enabled": True,
            "decision": decision,
            "reason_codes": reason_codes,
            "message": message,
            "thresholds": thresholds,
            "derived": derived,
            "allowed_notional": derived.get("allowed_notional"),
            "snapshot": snapshot_payload,
        }

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

        raw = self._safe_dict(live_result.get("raw"))
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
        payload = self._safe_dict(intent.payload)
        executable_plan = self._safe_dict(payload.get("executable_plan"))
        quality_snapshot = self._safe_dict(intent.quality_snapshot)
        sizing_mode = str(getattr(self.settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R") or "NOTIONAL_PER_R").strip().upper()
        reference_price = self._float_or(
            executable_plan.get("entry_limit_price")
            or executable_plan.get("entry_trigger_price")
            or getattr(plan, "entry_price", 0.0)
        )
        stop_price = self._float_or(executable_plan.get("stop_price") or getattr(plan, "sl", 0.0))
        default_step = self._float_or(getattr(self.settings, "binance_live_quantity_step", 0.001), 0.001)
        default_min_quantity = self._float_or(getattr(self.settings, "binance_live_min_quantity", default_step), default_step)
        step = default_step
        min_quantity = default_min_quantity
        symbol_rules_source = "settings_default"
        symbol_rules_error: str | None = None
        symbol_rules, symbol_rules_error = self._live_symbol_rules(str(plan.symbol or "").upper())
        if symbol_rules:
            step = self._float_or(symbol_rules.get("quantity_step"), default_step)
            min_quantity = self._float_or(symbol_rules.get("min_quantity"), default_min_quantity or step)
            symbol_rules_source = str(symbol_rules.get("source") or "binance_exchange_info")
        step = max(step, 1e-9)
        min_quantity = max(min_quantity, step)

        sizing_details = {
            "sizing_mode": sizing_mode,
            "recommended_risk_r": self._float_or(quality_snapshot.get("recommended_risk_r")),
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
                parsed_tick_size = self._maybe_float(tick_size)
                if parsed_tick_size is not None and parsed_tick_size > 0.0:
                    sizing_details["tick_size"] = round(parsed_tick_size, 8)
        if reference_price <= 0.0:
            return None, sizing_details, "Live submit requires a positive reference price."
        max_position_notional = 0.0
        if sizing_mode == "RISK_PCT":
            account_equity_usdt = self._float_or(getattr(self.settings, "auto_trading_live_account_equity_usdt", 0.0))
            risk_per_trade_pct = self._float_or(getattr(self.settings, "auto_trading_live_risk_per_trade_pct", 0.0))
            usable_margin_fraction = self._float_or(getattr(self.settings, "auto_trading_live_usable_margin_fraction", 0.0))
            leverage_cap = self._float_or(getattr(self.settings, "auto_trading_live_leverage_cap", 0.0))
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
            max_position_notional = self._float_or(
                executable_plan.get(
                    "max_position_notional",
                    quality_snapshot.get("max_position_notional", 0.0),
                )
            )
            if max_position_notional <= 0.0:
                max_position_notional = round(
                    max(self._float_or(quality_snapshot.get("recommended_risk_r")), 0.0)
                    * self._float_or(self.settings.auto_trading_notional_per_r),
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

        max_position_notional = self._apply_tranche_remaining_cap(
            intent=intent,
            max_position_notional=max_position_notional,
            sizing_details=sizing_details,
        )
        sizing_details["max_position_notional"] = round(max_position_notional, 4)
        if max_position_notional <= 0.0:
            return None, sizing_details, "Live submit has no remaining tranche notional to route."

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
        paper_lineage_override = bool(self._safe_dict(intent.approval_snapshot).get("paper_lineage_override_applied"))
        approval_bundle = self._safe_dict(
            self.approval_loader(
                plan.plan_id,
                requested_mode,
                paper_lineage_override=paper_lineage_override,
            )
        )
        approval = self._safe_dict(approval_bundle.get("approval"))
        try:
            approval_state = ApprovalState(str(approval.get("approval_state") or ApprovalState.BLOCKED.value))
        except ValueError:
            approval_state = ApprovalState.BLOCKED
        effective_mode = ExecutionPlanningService.coerce_execution_mode(
            approval.get("allowed_execution_mode"),
            default=requested_mode,
        )

        try:
            submit_decision = SubmitDecision(str(intent.submit_decision))
        except ValueError:
            submit_decision = None
        if submit_decision != SubmitDecision.SUBMIT:
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
                attachments={**self._safe_dict(adapter_result.attachments), "session_guidance": self._safe_dict(intent.session_guidance)},
                raw={
                    **self._safe_dict(adapter_result.raw),
                    "fill_results": fill_results,
                    "intent_snapshot": {"session_guidance": self._safe_dict(intent.session_guidance)},
                },
                submitted_at=datetime.now(timezone.utc),
                acknowledged_at=adapter_result.acknowledged_at,
                cancelled_at=adapter_result.cancelled_at,
            )
            self.submission_repo.add(row)
            tracker = self._lane_tracker()
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
                **self._safe_dict(row.attachments),
                "live_order_sizing": live_sizing,
                "session_guidance": self._safe_dict(intent.session_guidance),
            }
            row.raw = {
                **self._safe_dict(row.raw),
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
            **self._safe_dict(live_sizing),
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
                **self._safe_dict(row.attachments),
                "live_order_sizing": live_sizing,
                "session_guidance": self._safe_dict(intent.session_guidance),
            }
            row.raw = {
                **self._safe_dict(row.raw),
                "live_order_sizing": live_sizing,
            }
            return row, [], False

        liquidity_reference_price = float(
            normalized_live_price
            or live_sizing.get("reference_price")
            or getattr(plan, "entry_price", 0.0)
            or 0.0
        )
        liquidity_gate = self._live_liquidity_gate(
            symbol=plan.symbol,
            side=live_side,
            order_type=live_order_type,
            quantity=live_quantity,
            price=normalized_live_price if live_order_type == "LIMIT" else None,
            reference_price=liquidity_reference_price,
        )
        if bool(liquidity_gate.get("enabled")):
            live_sizing = {
                **self._safe_dict(live_sizing),
                "liquidity_gate_decision": str(liquidity_gate.get("decision") or ""),
            }
        if str(liquidity_gate.get("decision") or "PASS").upper() != "PASS":
            decision = str(liquidity_gate.get("decision") or "BLOCK").upper()
            live_tranche: dict[str, Any] = {}
            if decision == "SPLIT_REQUIRED":
                partial_quantity, adjusted_sizing, partial_error = self._partial_tranche_order(
                    intent=intent,
                    plan=plan,
                    live_quantity=live_quantity,
                    live_sizing=live_sizing,
                    liquidity_gate=liquidity_gate,
                    reference_price=liquidity_reference_price,
                )
                if partial_error is None and partial_quantity is not None:
                    live_quantity = partial_quantity
                    live_sizing = adjusted_sizing
                    live_tranche = self._safe_dict(adjusted_sizing.get("live_tranche"))
                    liquidity_gate = {
                        **self._safe_dict(liquidity_gate),
                        "decision": "SPLIT_PARTIAL_SUBMIT",
                        "message": "Live order size was reduced by liquidity gate and routed as a tranche.",
                    }
                    decision = "PASS"
                else:
                    liquidity_gate = {
                        **self._safe_dict(liquidity_gate),
                        "partial_submit_error": partial_error,
                    }
            if decision == "PASS":
                pass
            else:
                row = self._rejection_submission(
                    intent=intent,
                    plan=plan,
                    message=str(liquidity_gate.get("message") or "Live liquidity gate blocked the order."),
                    submit_status="LIVE_LIQUIDITY_SPLIT_REQUIRED" if decision == "SPLIT_REQUIRED" else "LIVE_LIQUIDITY_BLOCKED",
                    client_order_id=client_order_id,
                    requested_live=live,
                )
                row.attachments = {
                    **self._safe_dict(row.attachments),
                    "live_order_sizing": live_sizing,
                    "live_liquidity_gate": liquidity_gate,
                    "session_guidance": self._safe_dict(intent.session_guidance),
                }
                row.raw = {
                    **self._safe_dict(row.raw),
                    "live_order_sizing": live_sizing,
                    "live_liquidity_gate": liquidity_gate,
                }
                return row, [], False
        else:
            live_tranche = {}

        try:
            live_result_raw = self.live_submitter(
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
            if not isinstance(live_result_raw, Mapping):
                raise RuntimeError(f"live_submitter_malformed_response:{type(live_result_raw).__name__}")
            live_result = dict(live_result_raw)
        except Exception as exc:
            session = getattr(self.submission_repo, "db", None)
            if session is not None and not bool(getattr(session, "is_active", True)):
                session.rollback()
            live_submit_error = {
                "type": exc.__class__.__name__,
                "message": str(exc),
            }
            row = OrderSubmission(
                submission_id=f"sub_{uuid4().hex[:20]}",
                intent_id=intent.intent_id,
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                client_order_id=client_order_id,
                exchange_order_id=None,
                state=OrderLifecycleState.SUBMITTED.value,
                submit_status="LIVE_SUBMIT_ERROR",
                message=(
                    "Live submitter raised before exchange acknowledgement; reconcile the exchange "
                    f"before retrying: {live_submit_error['message']}"
                ),
                adapter="binance",
                execution_mode=effective_mode.value,
                side=live_side,
                order_type=live_order_type,
                reduce_only=False,
                requested_live=True,
                attachments={
                    "requires_reconciliation": True,
                    "reentry_blocked_until_reconciled": True,
                    "session_guidance": self._safe_dict(intent.session_guidance),
                    "live_order_sizing": live_sizing,
                    **({"live_tranche": live_tranche} if live_tranche else {}),
                    **({"live_liquidity_gate": liquidity_gate} if bool(liquidity_gate.get("enabled")) else {}),
                    "live_submit_error": live_submit_error,
                },
                raw={
                    "unknown_exchange_state": True,
                    "requires_reconciliation": True,
                    "live_order_sizing": live_sizing,
                    **({"live_tranche": live_tranche} if live_tranche else {}),
                    **({"live_liquidity_gate": liquidity_gate} if bool(liquidity_gate.get("enabled")) else {}),
                    "live_submit_error": live_submit_error,
                    "intent_snapshot": {"session_guidance": self._safe_dict(intent.session_guidance)},
                },
                submitted_at=datetime.now(timezone.utc),
            )
            self.submission_repo.add(row)
            return row, [], False
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
                **({"live_tranche": live_tranche} if live_tranche else {}),
                **({"live_liquidity_gate": liquidity_gate} if bool(liquidity_gate.get("enabled")) else {}),
                "session_guidance": self._safe_dict(intent.session_guidance),
            },
            raw={
                **live_result,
                "live_order_sizing": live_sizing,
                **({"live_tranche": live_tranche} if live_tranche else {}),
                **({"live_liquidity_gate": liquidity_gate} if bool(liquidity_gate.get("enabled")) else {}),
                "intent_snapshot": {"session_guidance": self._safe_dict(intent.session_guidance)},
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
                **self._safe_dict(row.attachments),
                "immediate_fill_ingested": True,
            }
            row.raw = {
                **self._safe_dict(row.raw),
                "fill_results": fill_results,
            }
        tracker = self._lane_tracker()
        tracker.record_submitted(is_variant=self._intent_is_transition_edge_variant(intent))
        return row, fill_results, False
