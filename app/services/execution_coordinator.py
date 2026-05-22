from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from datetime import datetime, timezone
import json
from math import isfinite
import time
from typing import Any, Callable
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.enums import (
    ApprovalState,
    ExecutionFillStage,
    ExecutionMode,
    ExitReason,
    OrderLifecycleState,
    SubmitDecision,
)
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
        live_balance_loader: Callable[[], Any] | None = None,
        live_mark_price_loader: Callable[..., dict[str, Any] | None] | None = None,
        live_account_protection_loader: Callable[[], dict[str, Any] | None] | None = None,
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
        self.live_balance_loader = live_balance_loader
        self.live_mark_price_loader = live_mark_price_loader
        self.live_account_protection_loader = live_account_protection_loader
        self.settings = settings or get_settings()
        self.paper_adapter = paper_adapter or PaperExecutionAdapter()
        self._live_symbol_rules_cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _client_order_id(intent_id: str) -> str:
        return f"intent-{intent_id[-16:]}"

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Mapping):
            return {str(key): ExecutionCoordinator._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [ExecutionCoordinator._json_safe(item) for item in value]
        try:
            json.dumps(value)
        except TypeError:
            return str(value)
        return value

    @staticmethod
    def _safe_dict(value: Any) -> dict[str, Any]:
        return ExecutionCoordinator._json_safe(dict(value)) if isinstance(value, Mapping) else {}

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
        if ExecutionCoordinator._safe_bool(executable_plan.get("transition_edge_variant_applied")):
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
            requested_live=self._safe_bool(requested_live),
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

    @staticmethod
    def _csv_upper(value: Any) -> list[str]:
        items = [item.strip().upper() for item in str(value or "").split(",")]
        return [item for item in items if item]

    def _balance_rows_from_snapshot(self, snapshot: Any) -> list[dict[str, Any]]:
        if isinstance(snapshot, list):
            return [self._safe_dict(item) for item in snapshot if self._safe_dict(item)]
        snapshot_payload = self._safe_dict(snapshot)
        rows = snapshot_payload.get("balances")
        if isinstance(rows, list):
            return [self._safe_dict(item) for item in rows if self._safe_dict(item)]
        return []

    def _live_account_equity(self) -> tuple[float, dict[str, Any], str | None]:
        configured_equity = self._float_or(getattr(self.settings, "auto_trading_live_account_equity_usdt", 0.0))
        sync_enabled = self._safe_bool(getattr(self.settings, "auto_trading_live_balance_sync_enabled", False))
        fail_closed = self._safe_bool(getattr(self.settings, "auto_trading_live_balance_sync_fail_closed", True), default=True)
        preferred_assets = self._csv_upper(getattr(self.settings, "auto_trading_live_balance_sync_assets", "USDT,USDC")) or [
            "USDT",
            "USDC",
        ]
        details: dict[str, Any] = {
            "configured_account_equity_usdt": round(configured_equity, 4),
            "balance_sync_enabled": bool(sync_enabled),
            "balance_sync_assets": preferred_assets,
        }
        if not sync_enabled:
            details["account_equity_source"] = "configured"
            return configured_equity, details, None

        details["balance_sync_fail_closed"] = bool(fail_closed)
        if self.live_balance_loader is None:
            details["balance_sync_error"] = "live_balance_loader_missing"
            if fail_closed:
                return 0.0, details, "Live balance sync is enabled but no balance loader is configured."
            details["account_equity_source"] = "configured_fallback"
            return configured_equity, details, None

        try:
            snapshot = self.live_balance_loader()
        except Exception as exc:  # pragma: no cover - defensive live-submit guard
            details["balance_sync_error"] = str(exc)
            if fail_closed:
                return 0.0, details, f"Live balance sync failed: {exc}"
            details["account_equity_source"] = "configured_fallback"
            return configured_equity, details, None

        rows = self._balance_rows_from_snapshot(snapshot)
        rows_by_asset = {str(row.get("asset") or row.get("a") or "").upper(): row for row in rows}
        details["balance_row_count"] = len(rows)
        for asset in preferred_assets:
            row = rows_by_asset.get(asset)
            if not row:
                continue
            available = self._maybe_float(
                row.get("availableBalance")
                or row.get("available_balance")
                or row.get("crossWalletBalance")
                or row.get("walletBalance")
                or row.get("balance")
            )
            if available is None or available <= 0.0:
                continue
            details.update(
                {
                    "account_equity_source": "binance_futures_available_balance",
                    "balance_asset": asset,
                    "balance_available_usdt": round(float(available), 4),
                }
            )
            wallet_balance = self._maybe_float(row.get("balance") or row.get("walletBalance") or row.get("wallet_balance"))
            if wallet_balance is not None:
                details["balance_wallet_usdt"] = round(float(wallet_balance), 4)
            return float(available), details, None

        details["balance_sync_error"] = "preferred_asset_available_balance_missing"
        if fail_closed:
            return 0.0, details, "Live balance sync did not find a positive available balance for the configured assets."
        details["account_equity_source"] = "configured_fallback"
        return configured_equity, details, None

    def _live_account_protection_gate(self) -> dict[str, Any]:
        enabled = self._safe_bool(
            getattr(self.settings, "auto_trading_live_account_protection_gate_enabled", True),
            default=True,
        )
        fail_closed = self._safe_bool(
            getattr(self.settings, "auto_trading_live_account_protection_gate_fail_closed", True),
            default=True,
        )
        details: dict[str, Any] = {
            "enabled": bool(enabled),
            "fail_closed": bool(fail_closed),
            "decision": "PASS",
            "reason": "disabled" if not enabled else "ok",
        }
        if not enabled:
            return details
        if self.live_account_protection_loader is None:
            details.update(
                {
                    "decision": "BLOCK" if fail_closed else "PASS",
                    "reason": "loader_not_configured",
                }
            )
            return details
        try:
            payload = self.live_account_protection_loader()
        except Exception as exc:  # pragma: no cover - defensive live-submit guard
            details.update(
                {
                    "decision": "BLOCK" if fail_closed else "PASS",
                    "reason": "account_protection_check_error",
                    "error": f"{exc.__class__.__name__}:{exc}",
                }
            )
            return details

        payload_dict = self._safe_dict(payload)
        if not payload_dict or "fail_count" not in payload_dict:
            details.update(
                {
                    "decision": "BLOCK" if fail_closed else "PASS",
                    "reason": "account_protection_payload_invalid",
                }
            )
            return details
        fail_count = int(self._float_or(payload_dict.get("fail_count")))
        warn_count = int(self._float_or(payload_dict.get("warn_count")))
        details.update(
            {
                "reason": "account_protection_failures" if fail_count > 0 else "ok",
                "overall_status": str(payload_dict.get("overall_status") or ""),
                "severity": str(payload_dict.get("severity") or ""),
                "fail_count": fail_count,
                "warn_count": warn_count,
                "open_position_count": int(self._float_or(payload_dict.get("open_position_count"))),
                "issues": list(payload_dict.get("issues") or [])[:10],
            }
        )
        if fail_count > 0:
            details["decision"] = "BLOCK"
        return details

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

    def _normalize_live_stop_price(
        self,
        *,
        plan: Plan,
        requested_price: float | None,
    ) -> tuple[float | None, dict[str, Any]]:
        if requested_price is None:
            return None, {}

        symbol = str(getattr(plan, "symbol", "") or "").upper()
        details: dict[str, Any] = {
            "price_role": "stop_loss",
            "requested_stop_price": round(float(requested_price), 8),
        }
        symbol_rules, symbol_rules_error = self._live_symbol_rules(symbol)
        if symbol_rules_error:
            details["price_rules_loader_error"] = symbol_rules_error
        tick_size = self._float_or((symbol_rules or {}).get("tick_size"), 0.0)
        if tick_size <= 0.0:
            details["price_rules_source"] = str((symbol_rules or {}).get("source") or "settings_passthrough")
            details["normalized_stop_price"] = round(float(requested_price), 8)
            return float(requested_price), details

        direction = str(getattr(plan, "direction", "") or "").lower()
        if direction == "short":
            normalized_price = self._round_up_to_step(float(requested_price), step=tick_size)
            rounding_mode = "round_up_for_short_stop"
        else:
            normalized_price = self._round_down_to_step(float(requested_price), step=tick_size)
            rounding_mode = "round_down_for_long_stop"
        details.update(
            {
                "direction": direction,
                "tick_size": round(tick_size, 8),
                "price_rules_source": str((symbol_rules or {}).get("source") or "binance_exchange_info"),
                "stop_rounding_mode": rounding_mode,
                "normalized_stop_price": round(float(normalized_price), 8),
            }
        )
        return float(normalized_price), details

    def _normalize_live_take_profit_price(
        self,
        *,
        plan: Plan,
        requested_price: float | None,
    ) -> tuple[float | None, dict[str, Any]]:
        if requested_price is None:
            return None, {}

        symbol = str(getattr(plan, "symbol", "") or "").upper()
        details: dict[str, Any] = {
            "price_role": "take_profit",
            "requested_take_profit_price": round(float(requested_price), 8),
        }
        symbol_rules, symbol_rules_error = self._live_symbol_rules(symbol)
        if symbol_rules_error:
            details["price_rules_loader_error"] = symbol_rules_error
        tick_size = self._float_or((symbol_rules or {}).get("tick_size"), 0.0)
        if tick_size <= 0.0:
            details["price_rules_source"] = str((symbol_rules or {}).get("source") or "settings_passthrough")
            details["normalized_take_profit_price"] = round(float(requested_price), 8)
            return float(requested_price), details

        direction = str(getattr(plan, "direction", "") or "").lower()
        if direction == "short":
            normalized_price = self._round_up_to_step(float(requested_price), step=tick_size)
            rounding_mode = "round_up_for_short_take_profit"
        else:
            normalized_price = self._round_down_to_step(float(requested_price), step=tick_size)
            rounding_mode = "round_down_for_long_take_profit"
        details.update(
            {
                "direction": direction,
                "tick_size": round(tick_size, 8),
                "price_rules_source": str((symbol_rules or {}).get("source") or "binance_exchange_info"),
                "take_profit_rounding_mode": rounding_mode,
                "normalized_take_profit_price": round(float(normalized_price), 8),
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

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value) if isfinite(float(value)) else bool(default)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return bool(default)

    def _binance_live_position_side(self, *, plan: Plan, side: str) -> str | None:
        mode = str(getattr(self.settings, "binance_live_position_side_mode", "ONE_WAY") or "ONE_WAY").strip().upper()
        mode = mode.replace("-", "_").replace(" ", "_")
        if mode not in {"HEDGE", "HEDGE_MODE", "DUAL", "DUAL_SIDE", "DUAL_SIDE_POSITION"}:
            return None
        direction = str(getattr(plan, "direction", "") or "").strip().lower()
        if direction == "long":
            return "LONG"
        if direction == "short":
            return "SHORT"
        return "LONG" if str(side or "").upper() == "BUY" else "SHORT"

    def _partial_submit_enabled(self) -> bool:
        return self._safe_bool(getattr(self.settings, "auto_trading_live_liquidity_gate_partial_submit_enabled", False))

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
        submitted_fraction = submitted_notional / target_notional if target_notional > 0.0 else 0.0
        min_target_fraction = max(
            0.0,
            self._float_or(
                getattr(self.settings, "auto_trading_live_liquidity_gate_min_tranche_target_fraction", 0.0),
            ),
        )
        if min_target_fraction > 0.0 and submitted_fraction + 1e-12 < min_target_fraction:
            return None, {}, "partial_submit_target_fraction_below_minimum"

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
            "submitted_target_fraction": round(submitted_fraction, 6),
            "min_target_fraction": round(min_target_fraction, 6),
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
            "original_normalized_notional": round(float(live_quantity or 0.0) * float(reference_price), 4),
            "original_max_position_notional": round(float(target_notional), 4),
            "normalized_quantity": round(float(partial_quantity), 8),
            "normalized_notional": round(submitted_notional, 4),
            "max_position_notional": round(submitted_notional, 4),
            "liquidity_tranche_reduction_notional": round(max(float(target_notional) - submitted_notional, 0.0), 4),
            "liquidity_tranche_submitted_fraction": round(submitted_fraction, 6),
            "liquidity_tranche_min_target_fraction": round(min_target_fraction, 6),
            "live_tranche": live_tranche,
        }
        if str(adjusted_sizing.get("sizing_mode") or "").strip().upper() == "RISK_PCT":
            stop_pct = self._float_or(adjusted_sizing.get("stop_pct"))
            account_equity_usdt = self._float_or(adjusted_sizing.get("account_equity_usdt"))
            sizing_equity_usdt = self._float_or(adjusted_sizing.get("sizing_equity_usdt"), account_equity_usdt)
            actual_risk_usdt = submitted_notional * stop_pct
            adjusted_sizing["actual_risk_usdt"] = round(actual_risk_usdt, 4)
            adjusted_sizing["actual_risk_pct"] = round(
                actual_risk_usdt / account_equity_usdt if account_equity_usdt > 0.0 else 0.0,
                6,
            )
            adjusted_sizing["actual_risk_pct_of_sizing_equity"] = round(
                actual_risk_usdt / sizing_equity_usdt if sizing_equity_usdt > 0.0 else 0.0,
                6,
            )
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
        if not self._safe_bool(getattr(self.settings, "auto_trading_live_liquidity_gate_enabled", False)):
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
        fail_closed = self._safe_bool(getattr(self.settings, "auto_trading_live_liquidity_gate_fail_closed", True), default=True)
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
            slippage_allowed_notional = self._maybe_float(snapshot_payload.get("market_slippage_allowed_notional"))
            if slippage_allowed_notional is not None and slippage_allowed_notional > 0.0:
                notional_caps.append(
                    {
                        "source": "market_slippage",
                        "allowed_notional": slippage_allowed_notional,
                    }
                )

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

    def _estimated_entry_reference_price(
        self,
        *,
        side: str,
        order_type: str,
        normalized_price: float | None,
        liquidity_gate: dict[str, Any],
        live_sizing: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        snapshot = self._safe_dict(liquidity_gate.get("snapshot"))
        normalized_side = str(side or "").upper()
        normalized_order_type = str(order_type or "").upper()
        candidates: list[tuple[str, Any]] = []

        marketable_now = self._safe_bool(snapshot.get("marketable_now"), default=normalized_order_type != "LIMIT")
        if normalized_order_type != "LIMIT" or marketable_now:
            candidates.append(("market_fill_avg_price", snapshot.get("market_fill_avg_price")))
            if normalized_side == "BUY":
                candidates.append(("best_ask", snapshot.get("best_ask")))
            elif normalized_side == "SELL":
                candidates.append(("best_bid", snapshot.get("best_bid")))
            candidates.append(("mid_price", snapshot.get("mid_price")))
        else:
            candidates.append(("normalized_limit_price", normalized_price))

        candidates.extend(
            [
                ("normalized_live_price", normalized_price),
                ("sizing_reference_price", live_sizing.get("reference_price")),
            ]
        )
        for source, value in candidates:
            parsed = self._maybe_float(value)
            if parsed is not None and parsed > 0.0:
                return float(parsed), {"reference_price_source": source, "reference_price": round(float(parsed), 8)}
        return 0.0, {"reference_price_source": "unavailable", "reference_price": 0.0}

    def _live_stop_distance_guard(
        self,
        *,
        plan: Plan,
        stop_price: float,
        reference_price: float,
        context: str,
    ) -> dict[str, Any]:
        enabled = self._safe_bool(getattr(self.settings, "auto_trading_live_stop_precheck_enabled", True), default=True)
        fail_closed = self._safe_bool(
            getattr(self.settings, "auto_trading_live_stop_precheck_fail_closed", True),
            default=True,
        )
        min_cushion_bps = max(
            self._float_or(getattr(self.settings, "auto_trading_live_stop_precheck_min_cushion_bps", 5.0), 5.0),
            0.0,
        )
        min_tick_cushion = max(
            self._int_or(getattr(self.settings, "auto_trading_live_stop_precheck_min_tick_cushion", 0), 0),
            0,
        )
        details: dict[str, Any] = {
            "enabled": bool(enabled),
            "decision": "PASS",
            "reason_codes": [],
            "context": str(context or ""),
            "reference_price": round(float(reference_price or 0.0), 8),
            "stop_price": round(float(stop_price or 0.0), 8),
            "min_cushion_bps": round(min_cushion_bps, 4),
            "min_tick_cushion": int(min_tick_cushion),
        }
        if not enabled:
            details["reason"] = "disabled"
            return details
        if reference_price <= 0.0 or stop_price <= 0.0:
            details.update(
                {
                    "decision": "BLOCK" if fail_closed else "PASS",
                    "reason_codes": ["stop_reference_price_unavailable"],
                    "message": "Live entry blocked because stop distance could not be checked.",
                }
            )
            return details

        direction = str(getattr(plan, "direction", "") or "").lower()
        if direction == "short":
            cushion_bps = (float(stop_price) - reference_price) / reference_price * 10_000.0
            immediate_trigger = float(stop_price) <= reference_price
        else:
            cushion_bps = (reference_price - float(stop_price)) / reference_price * 10_000.0
            immediate_trigger = float(stop_price) >= reference_price
        details["stop_cushion_bps"] = round(float(cushion_bps), 4)
        details["direction"] = direction

        if immediate_trigger:
            details.update(
                {
                    "decision": "BLOCK",
                    "reason_codes": ["stop_would_immediately_trigger"],
                    "message": "Live order blocked because the stop is already on the trigger side of the reference price.",
                }
            )
            return details
        symbol_rules, symbol_rules_error = self._live_symbol_rules(str(getattr(plan, "symbol", "") or "").upper())
        if symbol_rules_error:
            details["tick_rules_loader_error"] = symbol_rules_error
        tick_size = self._float_or((symbol_rules or {}).get("tick_size"), 0.0)
        if tick_size > 0.0:
            stop_cushion_ticks = abs(reference_price - float(stop_price)) / tick_size
            details["tick_size"] = round(float(tick_size), 8)
            details["stop_cushion_ticks"] = round(float(stop_cushion_ticks), 4)
            details["tick_rules_source"] = str((symbol_rules or {}).get("source") or "binance_exchange_info")
            if min_tick_cushion > 0 and stop_cushion_ticks + 1e-9 < float(min_tick_cushion):
                normalized_context = str(context or "").lower()
                if normalized_context == "actual_fill":
                    too_close_reason = "stop_too_close_to_actual_fill_tick_cushion"
                elif normalized_context == "mark_price":
                    too_close_reason = "stop_too_close_to_mark_price_tick_cushion"
                else:
                    too_close_reason = "stop_too_close_to_estimated_fill_tick_cushion"
                details.update(
                    {
                        "decision": "BLOCK",
                        "reason_codes": [too_close_reason],
                        "message": (
                            "Live order blocked because the stop is too close to the reference price "
                            f"({stop_cushion_ticks:.2f} ticks < {min_tick_cushion} ticks)."
                        ),
                    }
                )
                return details
        if cushion_bps < min_cushion_bps:
            normalized_context = str(context or "").lower()
            if normalized_context == "actual_fill":
                too_close_reason = "stop_too_close_to_actual_fill"
            elif normalized_context == "mark_price":
                too_close_reason = "stop_too_close_to_mark_price"
            else:
                too_close_reason = "stop_too_close_to_estimated_fill"
            details.update(
                {
                    "decision": "BLOCK",
                    "reason_codes": [too_close_reason],
                    "message": (
                        "Live order blocked because the stop is too close to the reference price "
                        f"({cushion_bps:.2f}bps < {min_cushion_bps:.2f}bps)."
                    ),
                }
            )
            return details

        details["message"] = "Live stop distance guard passed."
        return details

    def _live_stop_precheck(
        self,
        *,
        plan: Plan,
        live_side: str,
        live_order_type: str,
        normalized_live_price: float | None,
        liquidity_gate: dict[str, Any],
        live_sizing: dict[str, Any],
        position_side: str | None = None,
    ) -> dict[str, Any]:
        enabled = self._safe_bool(getattr(self.settings, "auto_trading_live_stop_precheck_enabled", True), default=True)
        fail_closed = self._safe_bool(
            getattr(self.settings, "auto_trading_live_stop_precheck_fail_closed", True),
            default=True,
        )
        min_cushion_bps = max(
            self._float_or(getattr(self.settings, "auto_trading_live_stop_precheck_min_cushion_bps", 5.0), 5.0),
            0.0,
        )
        details: dict[str, Any] = {
            "enabled": bool(enabled),
            "decision": "PASS",
            "reason_codes": [],
            "min_cushion_bps": round(min_cushion_bps, 4),
        }
        if not enabled:
            details["reason"] = "disabled"
            return details

        close_side = self._live_close_side(plan)
        stop_price, stop_price_details = self._normalize_live_stop_price(
            plan=plan,
            requested_price=self._maybe_float(getattr(plan, "sl", None)),
        )
        details.update(
            {
                "close_side": close_side,
                "entry_side": str(live_side or "").upper(),
                "entry_order_type": str(live_order_type or "").upper(),
                "stop_price": round(float(stop_price or 0.0), 8),
                "stop_price_details": stop_price_details,
            }
        )
        if stop_price is None or stop_price <= 0.0:
            details.update(
                {
                    "decision": "BLOCK" if fail_closed else "PASS",
                    "reason_codes": ["stop_price_missing"],
                    "message": "Live entry blocked because stop price is missing.",
                }
            )
            return details

        reference_price, reference_details = self._estimated_entry_reference_price(
            side=live_side,
            order_type=live_order_type,
            normalized_price=normalized_live_price,
            liquidity_gate=liquidity_gate,
            live_sizing=live_sizing,
        )
        details.update(reference_details)
        if reference_price <= 0.0:
            details.update(
                {
                    "decision": "BLOCK" if fail_closed else "PASS",
                    "reason_codes": ["stop_reference_price_unavailable"],
                    "message": "Live entry blocked because stop precheck has no current reference price.",
                }
            )
            return details

        estimated_guard = self._live_stop_distance_guard(
            plan=plan,
            stop_price=float(stop_price),
            reference_price=reference_price,
            context="estimated_fill",
        )
        precheck = {**details, **estimated_guard}
        if str(estimated_guard.get("decision") or "PASS").upper() != "PASS":
            return precheck

        mark_price_guard = self._live_stop_mark_price_guard(
            plan=plan,
            stop_price=float(stop_price),
            position_side=position_side,
            working_type=str(getattr(self.settings, "auto_trading_live_stop_working_type", "MARK_PRICE") or "MARK_PRICE").upper(),
        )
        precheck["mark_price_stop_guard"] = mark_price_guard
        if str(mark_price_guard.get("decision") or "PASS").upper() != "PASS":
            return {
                **precheck,
                **mark_price_guard,
                "estimated_stop_guard": estimated_guard,
                "reason": str(mark_price_guard.get("reason") or "mark_price_stop_guard_blocked"),
                "message": str(mark_price_guard.get("message") or "Live entry blocked because the stop is too close to mark price."),
            }
        return precheck

    def _live_stop_mark_price_guard(
        self,
        *,
        plan: Plan,
        stop_price: float,
        position_side: str | None,
        working_type: str,
    ) -> dict[str, Any]:
        enabled = self._safe_bool(
            getattr(self.settings, "auto_trading_live_stop_mark_price_guard_enabled", True),
            default=True,
        )
        details: dict[str, Any] = {
            "enabled": bool(enabled),
            "decision": "PASS",
            "reason": "ok",
            "working_type": str(working_type or "").upper(),
            "symbol": str(getattr(plan, "symbol", "") or "").upper(),
            "position_side": self._expected_live_position_side(plan=plan, position_side=position_side),
        }
        if not enabled:
            details["reason"] = "disabled"
            return details
        if str(working_type or "").upper() != "MARK_PRICE":
            details["reason"] = "working_type_not_mark_price"
            return details
        if self.live_mark_price_loader is None:
            details["reason"] = "mark_price_loader_missing"
            return details

        try:
            snapshot = self.live_mark_price_loader(
                symbol=details["symbol"],
                position_side=details["position_side"],
            )
        except Exception as exc:  # pragma: no cover - defensive live-submit guard
            details.update(
                {
                    "reason": "mark_price_loader_error",
                    "error": {"type": exc.__class__.__name__, "message": str(exc)},
                }
            )
            return details

        snapshot_dict = self._safe_dict(snapshot)
        mark_price = (
            self._maybe_float(snapshot_dict.get("mark_price"))
            or self._maybe_float(self._safe_dict(snapshot_dict.get("position")).get("mark_price"))
        )
        details["snapshot"] = snapshot_dict
        if mark_price is None or mark_price <= 0.0:
            details["reason"] = "mark_price_unavailable"
            return details

        guard = self._live_stop_distance_guard(
            plan=plan,
            stop_price=float(stop_price),
            reference_price=float(mark_price),
            context="mark_price",
        )
        return {**details, **guard, "reference_price_source": "mark_price"}

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
            "partial": status == "PARTIALLY_FILLED",
            "side": str(live_result.get("side") or ""),
            "order_type": str(live_result.get("order_type") or ""),
            "reduce_only": self._safe_bool(live_result.get("reduce_only")),
            "notes": {"submit_path": "execution_coordinator_live_submit"},
        }
        fill_payload.update(
            self._estimated_live_fill_fee_payload(
                live_result=live_result,
                fill_price=float(fill_price),
                fill_qty=float(executed_qty),
            )
        )
        return fill_id, float(fill_price), float(executed_qty), fill_payload

    @staticmethod
    def _live_close_side(plan: Plan) -> str:
        return "SELL" if str(plan.direction or "").lower() == "long" else "BUY"

    @staticmethod
    def _is_hedge_position_side(position_side: str | None) -> bool:
        return str(position_side or "").upper() in {"LONG", "SHORT"}

    @staticmethod
    def _expected_live_position_side(*, plan: Plan, position_side: str | None) -> str:
        normalized_side = str(position_side or "").upper()
        if normalized_side in {"LONG", "SHORT"}:
            return normalized_side
        return "LONG" if str(getattr(plan, "direction", "") or "").lower() == "long" else "SHORT"

    @staticmethod
    def _protection_client_order_id(role: str) -> str:
        normalized_role = "".join(ch for ch in str(role or "protect").lower() if ch.isalnum() or ch in {"_", "-"})
        normalized_role = normalized_role[:8] or "protect"
        return f"{normalized_role}_{uuid4().hex[:20]}"

    def _live_protection_quantity_rules(self, symbol: str) -> tuple[float, float, dict[str, Any]]:
        default_step = self._float_or(getattr(self.settings, "binance_live_quantity_step", 0.001), 0.001)
        default_min_quantity = self._float_or(getattr(self.settings, "binance_live_min_quantity", default_step), default_step)
        symbol_rules, symbol_rules_error = self._live_symbol_rules(symbol)
        step = self._float_or((symbol_rules or {}).get("quantity_step"), default_step)
        min_quantity = self._float_or((symbol_rules or {}).get("min_quantity"), default_min_quantity or step)
        details = {
            "quantity_step": round(max(step, 1e-9), 8),
            "min_quantity": round(max(min_quantity, step, 1e-9), 8),
            "symbol_rules_source": str((symbol_rules or {}).get("source") or "settings_default"),
        }
        if symbol_rules_error:
            details["symbol_rules_loader_error"] = symbol_rules_error
        return max(step, 1e-9), max(min_quantity, step, 1e-9), details

    def _live_tp_targets(self, *, plan: Plan, entry_quantity: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        step, min_quantity, rules = self._live_protection_quantity_rules(str(plan.symbol or "").upper())
        split = self._safe_dict(getattr(plan, "split", None))
        raw_targets = [
            ("tp1", getattr(plan, "tp1", None), self._float_or(split.get("tp1"), 0.0)),
            ("tp2", getattr(plan, "tp2", None), self._float_or(split.get("tp2"), 0.0)),
            ("tp3", getattr(plan, "tp3", None), self._float_or(split.get("tp3", split.get("runner")), 0.0)),
        ]
        if sum(max(float(weight or 0.0), 0.0) for _, _, weight in raw_targets) <= 0.0:
            raw_targets = [("tp1", getattr(plan, "tp1", None), 1.0)]

        remaining = self._round_down_to_step(entry_quantity, step=step)
        targets: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for label, price_value, weight in raw_targets:
            if remaining < min_quantity:
                break
            price = self._maybe_float(price_value)
            fraction = max(float(weight or 0.0), 0.0)
            if price is None or price <= 0.0 or fraction <= 0.0:
                skipped.append({"label": label, "reason": "invalid_price_or_split"})
                continue
            requested_qty = min(entry_quantity * fraction, remaining)
            quantity = self._round_down_to_step(requested_qty, step=step)
            if quantity < min_quantity:
                skipped.append(
                    {
                        "label": label,
                        "reason": "quantity_below_minimum",
                        "requested_quantity": round(requested_qty, 8),
                        **rules,
                    }
                )
                continue
            normalized_price, price_details = self._normalize_live_take_profit_price(
                plan=plan,
                requested_price=price,
            )
            if normalized_price is None or normalized_price <= 0.0:
                skipped.append({"label": label, "reason": "price_normalization_failed", "requested_price": price})
                continue
            targets.append(
                {
                    "label": label,
                    "price": float(normalized_price),
                    "quantity": float(quantity),
                    "split": round(fraction, 8),
                    "price_details": price_details,
                    **rules,
                }
            )
            remaining = self._round_down_to_step(remaining - quantity, step=step)
        return targets, skipped

    def _live_filled_order_payload(
        self,
        *,
        plan: Plan,
        live_result: dict[str, Any],
        client_order_id: str,
        source: str,
        notes: dict[str, Any] | None = None,
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
        fill_payload = {
            "source": source,
            "client_order_id": str(live_result.get("client_order_id") or client_order_id),
            "exchange_order_id": exchange_order_id,
            "submit_status": status,
            "partial": status == "PARTIALLY_FILLED",
            "side": str(live_result.get("side") or ""),
            "order_type": str(live_result.get("order_type") or ""),
            "reduce_only": self._safe_bool(live_result.get("reduce_only")),
            "notes": dict(notes or {}),
        }
        fill_payload.update(
            self._estimated_live_fill_fee_payload(
                live_result=live_result,
                fill_price=float(fill_price),
                fill_qty=float(executed_qty),
            )
        )
        return fill_anchor, float(fill_price), float(executed_qty), fill_payload

    def _estimated_live_fill_fee_payload(
        self,
        *,
        live_result: dict[str, Any],
        fill_price: float,
        fill_qty: float,
    ) -> dict[str, Any]:
        raw = self._safe_dict(live_result.get("raw"))
        notional = (
            self._maybe_float(live_result.get("cum_quote"))
            or self._maybe_float(raw.get("cumQuote"))
            or self._maybe_float(raw.get("cum_quote"))
            or max(float(fill_price), 0.0) * max(float(fill_qty), 0.0)
        )
        if notional <= 0.0:
            return {
                "fee": 0.0,
                "fee_source": "estimated_fee_unavailable",
                "fee_notional": 0.0,
            }
        order_type = str(live_result.get("order_type") or raw.get("type") or "").upper()
        fee_bps = (
            self._float_or(getattr(self.settings, "maker_fee_bps", 2.0), 2.0)
            if order_type == "LIMIT"
            else self._float_or(getattr(self.settings, "taker_fee_bps", 4.0), 4.0)
        )
        fee = float(notional) * max(float(fee_bps), 0.0) / 10_000.0
        return {
            "fee": round(fee, 8),
            "fee_source": "estimated_from_config",
            "fee_bps": round(float(fee_bps), 6),
            "fee_notional": round(float(notional), 8),
            "fee_side": "one_way",
        }

    def _verify_live_protection_after_attach(
        self,
        *,
        plan: Plan,
        position_side: str | None,
        live: bool,
        parent_client_order_id: str,
        protection_kind: str,
    ) -> dict[str, Any]:
        normalized_kind = str(protection_kind or "").strip().lower()
        take_profit_kind = normalized_kind in {"take_profit", "tp", "target"}
        flag_name = "has_take_profit" if take_profit_kind else "has_stop"
        missing_issue_type = "missing_take_profit_protection" if take_profit_kind else "missing_stop_protection"
        confirmed_reason = "take_profit_protection_confirmed" if take_profit_kind else "stop_protection_confirmed"
        missing_reason = "matched_position_missing_take_profit" if take_profit_kind else "matched_position_missing_stop"
        issue_reason = "confirmed_missing_take_profit_protection" if take_profit_kind else "confirmed_missing_stop_protection"
        enabled_attr = (
            "auto_trading_live_take_profit_verify_after_attach_enabled"
            if take_profit_kind
            else "auto_trading_live_protection_verify_after_attach_enabled"
        )
        enabled = self._safe_bool(
            getattr(self.settings, enabled_attr, True),
            default=True,
        )
        fail_closed = self._safe_bool(
            getattr(self.settings, "auto_trading_live_protection_verify_fail_closed", True),
            default=True,
        )
        attempts = max(int(self._float_or(getattr(self.settings, "auto_trading_live_protection_verify_attempts", 3), 3)), 1)
        sleep_seconds = max(
            self._float_or(getattr(self.settings, "auto_trading_live_protection_verify_sleep_seconds", 0.5), 0.5),
            0.0,
        )
        symbol = str(getattr(plan, "symbol", "") or "").upper()
        expected_side = self._expected_live_position_side(plan=plan, position_side=position_side)
        details: dict[str, Any] = {
            "enabled": bool(enabled),
            "decision": "PASS",
            "reason": "disabled" if not enabled else "ok",
            "fail_closed": bool(fail_closed),
            "protection_kind": "take_profit" if take_profit_kind else "stop",
            "symbol": symbol,
            "position_side": expected_side,
            "attempts": attempts,
            "sleep_seconds": round(sleep_seconds, 4),
            "parent_client_order_id": parent_client_order_id,
        }
        if not enabled:
            return details
        if not live:
            details.update({"decision": "SKIP", "reason": "not_live"})
            return details
        if self.live_account_protection_loader is None:
            details.update(
                {
                    "decision": "BLOCK" if fail_closed else "SKIP",
                    "reason": "account_protection_loader_missing",
                }
            )
            return details

        last_error: dict[str, str] | None = None
        last_payload_summary: dict[str, Any] = {}
        for attempt in range(1, attempts + 1):
            details["attempt"] = attempt
            try:
                payload = self.live_account_protection_loader()
            except Exception as exc:  # pragma: no cover - defensive live-submit guard
                last_error = {"type": exc.__class__.__name__, "message": str(exc)}
                details["last_error"] = last_error
            else:
                payload_dict = self._safe_dict(payload)
                issues = [self._safe_dict(item) for item in list(payload_dict.get("issues") or [])]
                positions = [self._safe_dict(item) for item in list(payload_dict.get("positions") or [])]
                last_payload_summary = {
                    "overall_status": str(payload_dict.get("overall_status") or ""),
                    "severity": str(payload_dict.get("severity") or ""),
                    "fail_count": int(self._float_or(payload_dict.get("fail_count"))),
                    "warn_count": int(self._float_or(payload_dict.get("warn_count"))),
                    "open_position_count": int(self._float_or(payload_dict.get("open_position_count"))),
                    "open_order_count": int(self._float_or(payload_dict.get("open_order_count"))),
                }
                details["last_payload_summary"] = last_payload_summary

                for issue in issues:
                    issue_symbol = str(issue.get("symbol") or "").upper()
                    issue_side = str(issue.get("position_side") or "").upper()
                    issue_type = str(issue.get("type") or "").lower()
                    if issue_symbol == symbol and issue_side in {"", expected_side} and issue_type == missing_issue_type:
                        details.update(
                            {
                                "decision": "BLOCK",
                                "reason": issue_reason,
                                "issue": issue,
                            }
                        )
                        return details

                matched_position = None
                for position in positions:
                    position_symbol = str(position.get("symbol") or "").upper()
                    position_side_value = str(position.get("position_side") or position.get("side") or "").upper()
                    if position_symbol == symbol and position_side_value == expected_side:
                        matched_position = position
                        break

                if matched_position is None:
                    details.update(
                        {
                            "decision": "PASS",
                            "reason": "no_matching_open_position",
                        }
                    )
                    return details

                if self._safe_bool(matched_position.get(flag_name), default=False):
                    details.update(
                        {
                            "decision": "PASS",
                            "reason": confirmed_reason,
                            "position": matched_position,
                        }
                    )
                    return details

                details.update(
                    {
                        "decision": "BLOCK",
                        "reason": missing_reason,
                        "position": matched_position,
                    }
                )
                return details

            if attempt < attempts and sleep_seconds > 0.0:
                time.sleep(sleep_seconds)

        details.update(
            {
                "decision": "BLOCK" if fail_closed else "SKIP",
                "reason": "verification_error" if last_error else "verification_inconclusive",
                "last_payload_summary": last_payload_summary,
            }
        )
        if last_error:
            details["last_error"] = last_error
        return details

    def _emergency_flatten_after_protection_failure(
        self,
        *,
        plan: Plan,
        entry_quantity: float,
        close_side: str,
        position_side: str | None,
        hedge_mode: bool,
        parent_client_order_id: str,
        failure_reason: str,
        errors: list[dict[str, Any]],
        live: bool,
    ) -> dict[str, Any]:
        enabled = self._safe_bool(
            getattr(self.settings, "auto_trading_live_protection_failure_flatten_enabled", True),
            default=True,
        )
        if not enabled:
            return {
                "status": "DISABLED",
                "reason": "protection_failure_flatten_disabled",
                "requires_reconciliation": True,
            }

        step, min_quantity, rules = self._live_protection_quantity_rules(str(plan.symbol or "").upper())
        quantity = self._round_down_to_step(entry_quantity, step=step)
        if quantity < min_quantity:
            return {
                "status": "SKIPPED",
                "reason": "flatten_quantity_below_minimum",
                "quantity": round(quantity, 8),
                **rules,
                "requires_reconciliation": True,
            }

        client_order_id = self._protection_client_order_id("flat")
        try:
            flatten_result = self.live_submitter(
                symbol=str(plan.symbol or "").upper(),
                side=close_side,
                order_type="MARKET",
                quantity=float(quantity),
                price=None,
                stop_price=None,
                time_in_force="GTC",
                reduce_only=False if hedge_mode else True,
                position_side=position_side,
                close_position=False,
                working_type=None,
                order_purpose="live_protection:emergency_flatten",
                parent_client_order_id=parent_client_order_id,
                client_order_id=client_order_id,
                plan_id=plan.plan_id,
                live=live,
                new_order_resp_type="RESULT",
            )
        except Exception as exc:
            return {
                "status": "ERROR",
                "reason": "emergency_flatten_submit_failed",
                "client_order_id": client_order_id,
                "quantity": float(quantity),
                "error": {"type": exc.__class__.__name__, "message": str(exc)},
                "requires_reconciliation": True,
            }

        normalized_result = self._safe_dict(flatten_result)
        fill_payload = self._live_filled_order_payload(
            plan=plan,
            live_result=normalized_result,
            client_order_id=client_order_id,
            source="live_protection_failure_flatten",
            notes={
                "failure_reason": failure_reason,
                "protection_errors": errors,
                "parent_client_order_id": parent_client_order_id,
            },
        )
        fill_ingest = None
        if fill_payload is not None:
            fill_anchor, fill_price, fill_qty, payload = fill_payload
            status = str(normalized_result.get("status") or "").upper()
            stage = ExecutionFillStage.CLOSED if status == "FILLED" else ExecutionFillStage.PARTIAL_EXIT
            payload = {
                **payload,
                "exit_reason": ExitReason.RISK_LOCK_FLATTEN.value,
                "reason": "live_protection_failure_flatten",
            }
            fill_ingest = self.fill_ingest(
                fill_id=f"binance_emergency_flatten_{fill_anchor}_{status.lower()}",
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                stage=stage,
                fill_ts=datetime.now(timezone.utc),
                price=fill_price,
                qty=fill_qty,
                fee=self._float_or(payload.get("fee"), 0.0),
                payload=payload,
            )

        accepted = self._safe_bool(self._safe_dict(fill_ingest).get("accepted")) if fill_ingest is not None else False
        fully_closed = (
            accepted
            and str(self._safe_dict(fill_ingest).get("stage") or "") == ExecutionFillStage.CLOSED.value
        )
        return {
            "status": "FILLED" if fully_closed else str(normalized_result.get("status") or "SUBMITTED").upper(),
            "reason": "emergency_flatten_submitted",
            "client_order_id": client_order_id,
            "quantity": float(quantity),
            "result": normalized_result,
            "fill_ingest": fill_ingest,
            "requires_reconciliation": not fully_closed,
        }

    def attach_live_protection_orders(
        self,
        *,
        plan: Plan,
        entry_quantity: float,
        entry_price: float | None = None,
        position_side: str | None,
        parent_client_order_id: str,
        live: bool = True,
    ) -> dict[str, Any]:
        enabled = self._safe_bool(getattr(self.settings, "auto_trading_live_protection_orders_enabled", True), default=True)
        if not enabled:
            return {"status": "DISABLED", "orders": [], "errors": [], "parent_client_order_id": parent_client_order_id}

        symbol = str(plan.symbol or "").upper()
        quantity = self._maybe_float(entry_quantity)
        if quantity is None or quantity <= 0.0:
            return {
                "status": "SKIPPED",
                "reason": "entry_quantity_missing",
                "orders": [],
                "errors": [],
                "parent_client_order_id": parent_client_order_id,
            }

        close_side = self._live_close_side(plan)
        live_position_side = position_side or self._binance_live_position_side(plan=plan, side=close_side)
        hedge_mode = self._is_hedge_position_side(live_position_side)
        stop_price, stop_price_details = self._normalize_live_stop_price(
            plan=plan,
            requested_price=self._maybe_float(getattr(plan, "sl", None)),
        )
        orders: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        if stop_price is None or stop_price <= 0.0:
            errors.append(
                {
                    "role": "stop_loss",
                    "type": "StopPriceMissing",
                    "message": "Live protection requires a positive stop price.",
                    "details": stop_price_details,
                }
            )
            emergency_flatten = self._emergency_flatten_after_protection_failure(
                plan=plan,
                entry_quantity=float(quantity),
                close_side=close_side,
                position_side=live_position_side,
                hedge_mode=hedge_mode,
                parent_client_order_id=parent_client_order_id,
                failure_reason="stop_price_missing",
                errors=errors,
                live=live,
            )
            flattened = (
                str(emergency_flatten.get("status") or "").upper() == "FILLED"
                and not self._safe_bool(emergency_flatten.get("requires_reconciliation"), default=True)
            )
            return {
                "status": "EMERGENCY_FLATTENED" if flattened else "FAILED",
                "reason": "stop_price_missing",
                "orders": [],
                "errors": errors,
                "emergency_flatten": emergency_flatten,
                "parent_client_order_id": parent_client_order_id,
                "requires_reconciliation": not flattened,
            }

        working_type = str(getattr(self.settings, "auto_trading_live_stop_working_type", "MARK_PRICE") or "MARK_PRICE").upper()
        entry_reference_price = self._maybe_float(entry_price)
        if entry_reference_price is not None and entry_reference_price > 0.0:
            actual_fill_stop_guard = self._live_stop_distance_guard(
                plan=plan,
                stop_price=float(stop_price),
                reference_price=float(entry_reference_price),
                context="actual_fill",
            )
            if str(actual_fill_stop_guard.get("decision") or "PASS").upper() != "PASS":
                errors.append(
                    {
                        "role": "stop_loss",
                        "type": "StopDistanceGuardBlocked",
                        "message": str(actual_fill_stop_guard.get("message") or "Stop is too close to actual fill."),
                        "details": actual_fill_stop_guard,
                    }
                )
                emergency_flatten = self._emergency_flatten_after_protection_failure(
                    plan=plan,
                    entry_quantity=float(quantity),
                    close_side=close_side,
                    position_side=live_position_side,
                    hedge_mode=hedge_mode,
                    parent_client_order_id=parent_client_order_id,
                    failure_reason="actual_fill_stop_distance_guard_blocked",
                    errors=errors,
                    live=live,
                )
                flattened = (
                    str(emergency_flatten.get("status") or "").upper() == "FILLED"
                    and not self._safe_bool(emergency_flatten.get("requires_reconciliation"), default=True)
                )
                return {
                    "status": "EMERGENCY_FLATTENED" if flattened else "FAILED",
                    "reason": "actual_fill_stop_distance_guard_blocked",
                    "orders": orders,
                    "errors": errors,
                    "actual_fill_stop_guard": actual_fill_stop_guard,
                    "emergency_flatten": emergency_flatten,
                    "parent_client_order_id": parent_client_order_id,
                    "requires_reconciliation": not flattened,
                }

        mark_price_stop_guard = self._live_stop_mark_price_guard(
            plan=plan,
            stop_price=float(stop_price),
            position_side=live_position_side,
            working_type=working_type,
        )
        if str(mark_price_stop_guard.get("decision") or "PASS").upper() != "PASS":
            errors.append(
                {
                    "role": "stop_loss",
                    "type": "StopMarkPriceGuardBlocked",
                    "message": str(mark_price_stop_guard.get("message") or "Stop is too close to mark price."),
                    "details": mark_price_stop_guard,
                }
            )
            emergency_flatten = self._emergency_flatten_after_protection_failure(
                plan=plan,
                entry_quantity=float(quantity),
                close_side=close_side,
                position_side=live_position_side,
                hedge_mode=hedge_mode,
                parent_client_order_id=parent_client_order_id,
                failure_reason="mark_price_stop_distance_guard_blocked",
                errors=errors,
                live=live,
            )
            flattened = (
                str(emergency_flatten.get("status") or "").upper() == "FILLED"
                and not self._safe_bool(emergency_flatten.get("requires_reconciliation"), default=True)
            )
            return {
                "status": "EMERGENCY_FLATTENED" if flattened else "FAILED",
                "reason": "mark_price_stop_distance_guard_blocked",
                "orders": orders,
                "errors": errors,
                "mark_price_stop_guard": mark_price_stop_guard,
                "emergency_flatten": emergency_flatten,
                "parent_client_order_id": parent_client_order_id,
                "requires_reconciliation": not flattened,
            }

        stop_order = {
            "role": "stop_loss",
            "client_order_id": self._protection_client_order_id("sl"),
            "order_type": "STOP_MARKET",
            "side": close_side,
            "stop_price": float(stop_price),
            "quantity": None,
            "close_position": True,
            "position_side": live_position_side,
            "working_type": working_type,
            "price_details": stop_price_details,
        }

        try:
            stop_result = self.live_submitter(
                symbol=symbol,
                side=close_side,
                order_type="STOP_MARKET",
                quantity=None,
                price=None,
                stop_price=float(stop_price),
                time_in_force="GTC",
                reduce_only=False,
                position_side=live_position_side,
                close_position=True,
                working_type=working_type,
                order_purpose="live_protection:stop_loss",
                parent_client_order_id=parent_client_order_id,
                client_order_id=stop_order["client_order_id"],
                plan_id=plan.plan_id,
                live=live,
                new_order_resp_type="ACK",
            )
            orders.append({**stop_order, "result": self._safe_dict(stop_result)})
        except Exception as exc:
            errors.append({"role": "stop_loss", "type": exc.__class__.__name__, "message": str(exc)})
            emergency_flatten = self._emergency_flatten_after_protection_failure(
                plan=plan,
                entry_quantity=float(quantity),
                close_side=close_side,
                position_side=live_position_side,
                hedge_mode=hedge_mode,
                parent_client_order_id=parent_client_order_id,
                failure_reason="stop_loss_attach_failed",
                errors=errors,
                live=live,
            )
            flattened = (
                str(emergency_flatten.get("status") or "").upper() == "FILLED"
                and not self._safe_bool(emergency_flatten.get("requires_reconciliation"), default=True)
            )
            return {
                "status": "EMERGENCY_FLATTENED" if flattened else "FAILED",
                "reason": "stop_loss_attach_failed",
                "orders": orders,
                "errors": errors,
                "emergency_flatten": emergency_flatten,
                "parent_client_order_id": parent_client_order_id,
                "requires_reconciliation": not flattened,
            }

        stop_verification = self._verify_live_protection_after_attach(
            plan=plan,
            position_side=live_position_side,
            live=live,
            parent_client_order_id=parent_client_order_id,
            protection_kind="stop",
        )
        if str(stop_verification.get("decision") or "PASS").upper() == "BLOCK":
            errors.append(
                {
                    "role": "stop_loss",
                    "type": "StopProtectionVerificationFailed",
                    "message": "Live stop protection was not confirmed after stop-order ACK.",
                    "details": stop_verification,
                }
            )
            emergency_flatten = self._emergency_flatten_after_protection_failure(
                plan=plan,
                entry_quantity=float(quantity),
                close_side=close_side,
                position_side=live_position_side,
                hedge_mode=hedge_mode,
                parent_client_order_id=parent_client_order_id,
                failure_reason="stop_loss_verify_failed",
                errors=errors,
                live=live,
            )
            flattened = (
                str(emergency_flatten.get("status") or "").upper() == "FILLED"
                and not self._safe_bool(emergency_flatten.get("requires_reconciliation"), default=True)
            )
            return {
                "status": "EMERGENCY_FLATTENED" if flattened else "FAILED",
                "reason": "stop_loss_verify_failed",
                "orders": orders,
                "errors": errors,
                "stop_verification": stop_verification,
                "emergency_flatten": emergency_flatten,
                "parent_client_order_id": parent_client_order_id,
                "requires_reconciliation": not flattened,
            }

        tp_enabled = self._safe_bool(getattr(self.settings, "auto_trading_live_tp_limit_attach_enabled", True), default=True)
        skipped_targets: list[dict[str, Any]] = []
        tp_verification: dict[str, Any] = {
            "enabled": False,
            "decision": "SKIP",
            "reason": "tp_limit_attach_disabled" if not tp_enabled else "no_tp_order_submitted",
        }
        if tp_enabled:
            tp_targets, skipped_targets = self._live_tp_targets(plan=plan, entry_quantity=float(quantity))
            for target in tp_targets:
                tp_order = {
                    "role": str(target["label"]),
                    "client_order_id": self._protection_client_order_id(str(target["label"])),
                    "order_type": "LIMIT",
                    "side": close_side,
                    "price": float(target["price"]),
                    "quantity": float(target["quantity"]),
                    "position_side": live_position_side,
                    "reduce_only": False if hedge_mode else True,
                    "tp_market_fallback_seconds": int(getattr(self.settings, "auto_trading_live_tp_market_fallback_seconds", 20) or 0),
                    "target": target,
                }
                try:
                    tp_result = self.live_submitter(
                        symbol=symbol,
                        side=close_side,
                        order_type="LIMIT",
                        quantity=float(target["quantity"]),
                        price=float(target["price"]),
                        stop_price=None,
                        time_in_force="GTC",
                        reduce_only=False if hedge_mode else True,
                        position_side=live_position_side,
                        close_position=False,
                        working_type=None,
                        order_purpose=f"live_protection:{target['label']}",
                        parent_client_order_id=parent_client_order_id,
                        client_order_id=tp_order["client_order_id"],
                        plan_id=plan.plan_id,
                        live=live,
                        new_order_resp_type="ACK",
                    )
                    orders.append({**tp_order, "result": self._safe_dict(tp_result)})
                except Exception as exc:
                    errors.append({"role": str(target["label"]), "type": exc.__class__.__name__, "message": str(exc)})

            attached_tp_order_count = sum(1 for order in orders if str(order.get("role") or "").startswith("tp"))
            if attached_tp_order_count > 0:
                tp_verification = self._verify_live_protection_after_attach(
                    plan=plan,
                    position_side=live_position_side,
                    live=live,
                    parent_client_order_id=parent_client_order_id,
                    protection_kind="take_profit",
                )
                if str(tp_verification.get("decision") or "PASS").upper() == "BLOCK":
                    errors.append(
                        {
                            "role": "take_profit",
                            "type": "TakeProfitProtectionVerificationFailed",
                            "message": "Live take-profit protection was not confirmed after take-profit order ACK.",
                            "details": tp_verification,
                        }
                    )

        status = "ATTACHED" if not errors else "PARTIAL"
        return {
            "status": status,
            "orders": orders,
            "errors": errors,
            "skipped_targets": skipped_targets,
            "parent_client_order_id": parent_client_order_id,
            "position_side": live_position_side,
            "close_side": close_side,
            "tp_limit_attach_enabled": tp_enabled,
            "stop_verification": stop_verification,
            "tp_verification": tp_verification,
            "requires_reconciliation": bool(errors),
        }

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
            "base_recommended_risk_r": self._float_or(quality_snapshot.get("base_recommended_risk_r")),
            "allocated_risk_r": self._float_or(quality_snapshot.get("allocated_risk_r")),
            "allocation_weight": self._float_or(quality_snapshot.get("allocation_weight"), 1.0),
            "risk_sizing_r": self._float_or(
                quality_snapshot.get("risk_sizing_r"),
                self._float_or(quality_snapshot.get("recommended_risk_r")),
            ),
            "risk_allocator": self._safe_dict(quality_snapshot.get("risk_allocator")),
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
            account_equity_usdt, account_equity_details, account_equity_error = self._live_account_equity()
            strategy_equity_cap_usdt = max(
                self._float_or(getattr(self.settings, "auto_trading_live_strategy_equity_cap_usdt", 0.0)),
                0.0,
            )
            sizing_equity_usdt = (
                min(account_equity_usdt, strategy_equity_cap_usdt)
                if strategy_equity_cap_usdt > 0.0
                else account_equity_usdt
            )
            risk_per_trade_pct = self._float_or(getattr(self.settings, "auto_trading_live_risk_per_trade_pct", 0.0))
            recommended_risk_r = max(self._float_or(quality_snapshot.get("recommended_risk_r")), 0.0)
            risk_sizing_r = max(
                self._float_or(quality_snapshot.get("risk_sizing_r"), recommended_risk_r),
                0.0,
            )
            applied_risk_multiplier = min(risk_sizing_r, 1.0)
            usable_margin_fraction = self._float_or(getattr(self.settings, "auto_trading_live_usable_margin_fraction", 0.0))
            leverage_cap = self._float_or(getattr(self.settings, "auto_trading_live_leverage_cap", 0.0))
            stop_pct = abs(reference_price - stop_price) / reference_price if reference_price > 0.0 else 0.0
            effective_risk_per_trade_pct = risk_per_trade_pct * applied_risk_multiplier
            target_risk_usdt = sizing_equity_usdt * effective_risk_per_trade_pct
            usable_margin_usdt = sizing_equity_usdt * usable_margin_fraction
            target_notional = target_risk_usdt / stop_pct if stop_pct > 0.0 else 0.0
            leverage_cap_notional = max(usable_margin_usdt, 0.0) * max(leverage_cap, 0.0)
            max_position_notional = min(target_notional, leverage_cap_notional) if leverage_cap_notional > 0.0 else 0.0
            required_leverage = target_notional / usable_margin_usdt if usable_margin_usdt > 0.0 else 0.0
            actual_risk_usdt = max_position_notional * stop_pct
            actual_risk_pct = actual_risk_usdt / account_equity_usdt if account_equity_usdt > 0.0 else 0.0
            actual_risk_pct_of_sizing_equity = (
                actual_risk_usdt / sizing_equity_usdt if sizing_equity_usdt > 0.0 else 0.0
            )
            leverage_capped = max_position_notional + 1e-12 < target_notional

            sizing_details.update(
                {
                    "account_equity_usdt": round(account_equity_usdt, 4),
                    **account_equity_details,
                    "strategy_equity_cap_usdt": round(strategy_equity_cap_usdt, 4),
                    "sizing_equity_usdt": round(sizing_equity_usdt, 4),
                    "strategy_equity_capped": bool(
                        strategy_equity_cap_usdt > 0.0 and sizing_equity_usdt + 1e-12 < account_equity_usdt
                    ),
                    "risk_per_trade_pct": round(risk_per_trade_pct, 6),
                    "recommended_risk_multiplier": round(recommended_risk_r, 6),
                    "risk_sizing_multiplier": round(risk_sizing_r, 6),
                    "applied_risk_multiplier": round(applied_risk_multiplier, 6),
                    "effective_risk_per_trade_pct": round(effective_risk_per_trade_pct, 6),
                    "risk_multiplier_capped": bool(risk_sizing_r > applied_risk_multiplier),
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
                    "actual_risk_pct_of_sizing_equity": round(actual_risk_pct_of_sizing_equity, 6),
                    "leverage_capped": bool(leverage_capped),
                    "sizing_status": "capped_by_leverage" if leverage_capped else "target_risk_matched",
                }
            )
            if account_equity_error:
                return None, sizing_details, account_equity_error
            if account_equity_usdt <= 0.0:
                return None, sizing_details, "Live risk sizing requires AUTO_TRADING_LIVE_ACCOUNT_EQUITY_USDT > 0."
            if sizing_equity_usdt <= 0.0:
                return None, sizing_details, "Live risk sizing requires a positive sizing equity."
            if risk_per_trade_pct <= 0.0:
                return None, sizing_details, "Live risk sizing requires AUTO_TRADING_LIVE_RISK_PER_TRADE_PCT > 0."
            if risk_sizing_r <= 0.0:
                return None, sizing_details, "Live risk sizing requires a positive risk_sizing_r."
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
        normalized_notional = normalized_quantity * reference_price
        sizing_details["normalized_notional"] = round(normalized_notional, 4)
        if sizing_mode == "RISK_PCT":
            stop_pct = self._float_or(sizing_details.get("stop_pct"))
            account_equity_usdt = self._float_or(sizing_details.get("account_equity_usdt"))
            sizing_equity_usdt = self._float_or(sizing_details.get("sizing_equity_usdt"), account_equity_usdt)
            normalized_actual_risk_usdt = normalized_notional * stop_pct
            normalized_actual_risk_pct = (
                normalized_actual_risk_usdt / account_equity_usdt if account_equity_usdt > 0.0 else 0.0
            )
            normalized_actual_risk_pct_of_sizing_equity = (
                normalized_actual_risk_usdt / sizing_equity_usdt if sizing_equity_usdt > 0.0 else 0.0
            )
            sizing_details["actual_risk_usdt"] = round(normalized_actual_risk_usdt, 4)
            sizing_details["actual_risk_pct"] = round(normalized_actual_risk_pct, 6)
            sizing_details["actual_risk_pct_of_sizing_equity"] = round(
                normalized_actual_risk_pct_of_sizing_equity,
                6,
            )
            sizing_details["quantity_rounding_loss_notional"] = round(
                max(max_position_notional - normalized_notional, 0.0),
                4,
            )
            sizing_details["quantity_rounding_loss_risk_usdt"] = round(
                max((max_position_notional - normalized_notional) * stop_pct, 0.0),
                4,
            )

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
        live = self._safe_bool(live)
        existing = self.submission_repo.latest_for_intent(intent_id)
        if existing is not None:
            existing_raw = self._safe_dict(existing.raw)
            fill_results = existing_raw.get("fill_results")
            return existing, list(fill_results) if isinstance(fill_results, list) else [], True

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
        paper_lineage_override = self._safe_bool(
            self._safe_dict(intent.approval_snapshot).get("paper_lineage_override_applied")
        )
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
        if self._safe_bool(self.settings.auto_trading_close_only) or self._safe_bool((approval.get("operating_lock") or {}).get("active")):
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
        if not self._safe_bool(self.settings.binance_trade_live_enabled):
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Binance live submit is disabled in settings.",
                submit_status="LIVE_DISABLED",
                client_order_id=client_order_id,
                requested_live=live,
            )
            return row, [], False

        account_protection_gate = self._live_account_protection_gate()
        if str(account_protection_gate.get("decision") or "PASS").upper() != "PASS":
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message="Live submit blocked because account protection audit has unresolved failures.",
                submit_status="LIVE_ACCOUNT_PROTECTION_BLOCKED",
                client_order_id=client_order_id,
                requested_live=live,
            )
            row.attachments = {
                **self._safe_dict(row.attachments),
                "live_account_protection_gate": account_protection_gate,
                "session_guidance": self._safe_dict(intent.session_guidance),
            }
            row.raw = {
                **self._safe_dict(row.raw),
                "live_account_protection_gate": account_protection_gate,
            }
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
        live_position_side = self._binance_live_position_side(plan=plan, side=live_side)
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
        liquidity_gate_enabled = self._safe_bool(liquidity_gate.get("enabled"))
        if liquidity_gate_enabled:
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

        stop_precheck = self._live_stop_precheck(
            plan=plan,
            live_side=live_side,
            live_order_type=live_order_type,
            normalized_live_price=normalized_live_price,
            liquidity_gate=liquidity_gate,
            live_sizing=live_sizing,
            position_side=live_position_side,
        )
        if str(stop_precheck.get("decision") or "PASS").upper() != "PASS":
            row = self._rejection_submission(
                intent=intent,
                plan=plan,
                message=str(stop_precheck.get("message") or "Live stop precheck blocked the order."),
                submit_status="LIVE_STOP_PRECHECK_BLOCKED",
                client_order_id=client_order_id,
                requested_live=live,
            )
            row.attachments = {
                **self._safe_dict(row.attachments),
                "live_order_sizing": live_sizing,
                "live_stop_precheck": stop_precheck,
                "session_guidance": self._safe_dict(intent.session_guidance),
                **({"live_position_side": live_position_side} if live_position_side else {}),
                **({"live_tranche": live_tranche} if live_tranche else {}),
                **({"live_liquidity_gate": liquidity_gate} if liquidity_gate_enabled else {}),
            }
            row.raw = {
                **self._safe_dict(row.raw),
                "live_order_sizing": live_sizing,
                "live_stop_precheck": stop_precheck,
                **({"live_liquidity_gate": liquidity_gate} if liquidity_gate_enabled else {}),
            }
            return row, [], False

        claim_submitted_at = datetime.now(timezone.utc)
        row = OrderSubmission(
            submission_id=f"sub_{uuid4().hex[:20]}",
            intent_id=intent.intent_id,
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            client_order_id=client_order_id,
            exchange_order_id=None,
            state=OrderLifecycleState.SUBMITTED.value,
            submit_status="LIVE_SUBMITTING",
            message="Live submit claimed locally before exchange call.",
            adapter="binance",
            execution_mode=effective_mode.value,
            side=live_side,
            order_type=live_order_type,
            reduce_only=False,
            requested_live=True,
            attachments={
                "live_submit_claimed": True,
                "session_guidance": self._safe_dict(intent.session_guidance),
                "live_order_sizing": live_sizing,
                "live_stop_precheck": stop_precheck,
                **({"live_position_side": live_position_side} if live_position_side else {}),
                **({"live_tranche": live_tranche} if live_tranche else {}),
                **({"live_liquidity_gate": liquidity_gate} if liquidity_gate_enabled else {}),
            },
            raw={
                "live_submit_claimed": True,
                "live_order_sizing": live_sizing,
                "live_stop_precheck": stop_precheck,
                **({"live_position_side": live_position_side} if live_position_side else {}),
                **({"live_tranche": live_tranche} if live_tranche else {}),
                **({"live_liquidity_gate": liquidity_gate} if liquidity_gate_enabled else {}),
                "intent_snapshot": {"session_guidance": self._safe_dict(intent.session_guidance)},
            },
            submitted_at=claim_submitted_at,
        )
        self.submission_repo.add(row)
        claim_session = getattr(self.submission_repo, "db", None)
        try:
            if claim_session is not None:
                claim_session.commit()
        except Exception as exc:
            if claim_session is not None:
                claim_session.rollback()
            existing_after_claim = self.submission_repo.latest_for_intent(intent.intent_id)
            if existing_after_claim is not None:
                existing_raw = self._safe_dict(existing_after_claim.raw)
                fill_results = existing_raw.get("fill_results")
                return existing_after_claim, list(fill_results) if isinstance(fill_results, list) else [], True
            raise RuntimeError(f"live_submit_claim_failed:{exc.__class__.__name__}:{exc}") from exc

        try:
            live_result_raw = self.live_submitter(
                symbol=plan.symbol,
                side=live_side,
                order_type=live_order_type,
                quantity=live_quantity,
                price=normalized_live_price if live_order_type == "LIMIT" else None,
                time_in_force="GTC",
                reduce_only=False,
                position_side=live_position_side,
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
            if session is not None and not self._safe_bool(getattr(session, "is_active", True), default=True):
                session.rollback()
            live_submit_error = {
                "type": exc.__class__.__name__,
                "message": str(exc),
            }
            row.state = OrderLifecycleState.SUBMITTED.value
            row.submit_status = "LIVE_SUBMIT_ERROR"
            row.message = (
                "Live submitter raised after local claim; reconcile the exchange "
                f"before retrying: {live_submit_error['message']}"
            )
            row.attachments = {
                **self._safe_dict(row.attachments),
                "requires_reconciliation": True,
                "reentry_blocked_until_reconciled": True,
                "session_guidance": self._safe_dict(intent.session_guidance),
                "live_order_sizing": live_sizing,
                **({"live_position_side": live_position_side} if live_position_side else {}),
                **({"live_tranche": live_tranche} if live_tranche else {}),
                **({"live_liquidity_gate": liquidity_gate} if liquidity_gate_enabled else {}),
                "live_submit_error": live_submit_error,
            }
            row.raw = {
                **self._safe_dict(row.raw),
                "unknown_exchange_state": True,
                "requires_reconciliation": True,
                "live_order_sizing": live_sizing,
                **({"live_position_side": live_position_side} if live_position_side else {}),
                **({"live_tranche": live_tranche} if live_tranche else {}),
                **({"live_liquidity_gate": liquidity_gate} if liquidity_gate_enabled else {}),
                "live_submit_error": live_submit_error,
                "intent_snapshot": {"session_guidance": self._safe_dict(intent.session_guidance)},
            }
            return row, [], False
        status = str(live_result.get("status") or "NEW").upper()
        state = self._terminal_state(status)
        acknowledged_at = datetime.now(timezone.utc) if state in {
            OrderLifecycleState.ACKNOWLEDGED,
            OrderLifecycleState.PARTIALLY_FILLED,
            OrderLifecycleState.FILLED,
        } else None
        cancelled_at = datetime.now(timezone.utc) if state == OrderLifecycleState.CANCELLED else None
        row.client_order_id = str(live_result.get("client_order_id") or client_order_id)
        row.exchange_order_id = str(live_result.get("order_id")) if live_result.get("order_id") is not None else None
        row.state = state.value
        row.submit_status = status
        row.message = "Live submit forwarded to Binance adapter."
        row.adapter = "binance"
        row.execution_mode = effective_mode.value
        row.side = str(live_result.get("side") or "")
        row.order_type = str(live_result.get("order_type") or "")
        row.reduce_only = self._safe_bool(live_result.get("reduce_only"))
        row.requested_live = True
        row.attachments = {
            **self._safe_dict(row.attachments),
            "status": "pending_attach",
            "live_order_sizing": live_sizing,
            **({"live_position_side": live_position_side} if live_position_side else {}),
            **({"live_tranche": live_tranche} if live_tranche else {}),
            **({"live_liquidity_gate": liquidity_gate} if liquidity_gate_enabled else {}),
            "session_guidance": self._safe_dict(intent.session_guidance),
        }
        row.raw = {
            **self._safe_dict(row.raw),
            **live_result,
            "live_order_sizing": live_sizing,
            **({"live_position_side": live_position_side} if live_position_side else {}),
            **({"live_tranche": live_tranche} if live_tranche else {}),
            **({"live_liquidity_gate": liquidity_gate} if liquidity_gate_enabled else {}),
            "intent_snapshot": {"session_guidance": self._safe_dict(intent.session_guidance)},
        }
        row.acknowledged_at = acknowledged_at
        row.cancelled_at = cancelled_at
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
                    fee=self._float_or(fill_payload.get("fee"), 0.0),
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
            protection_orders = self.attach_live_protection_orders(
                plan=plan,
                entry_quantity=fill_qty,
                entry_price=fill_price,
                position_side=live_position_side,
                parent_client_order_id=client_order_id,
                live=True,
            )
            row.attachments = {
                **self._safe_dict(row.attachments),
                "live_protection_orders": protection_orders,
                **({"requires_reconciliation": True} if self._safe_bool(protection_orders.get("requires_reconciliation")) else {}),
            }
            row.raw = {
                **self._safe_dict(row.raw),
                "live_protection_orders": protection_orders,
            }
            if self._safe_bool(protection_orders.get("requires_reconciliation")):
                row.message = "Live entry filled but protection order attachment needs reconciliation."
        elif state == OrderLifecycleState.ACKNOWLEDGED:
            row.attachments = {
                **self._safe_dict(row.attachments),
                "live_protection_orders": {
                    "status": "PENDING_ENTRY_FILL",
                    "parent_client_order_id": client_order_id,
                    "message": "Protection orders will attach after an entry fill is observed.",
                },
            }
        tracker = self._lane_tracker()
        tracker.record_submitted(is_variant=self._intent_is_transition_edge_variant(intent))
        return row, fill_results, False
