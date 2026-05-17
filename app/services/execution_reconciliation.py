from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.enums import ExecutionFillStage, LockScopeType, LockSeverity, PlanState, ReconciliationSeverity
from app.db.models import ExecutionReconciliationEvent, Plan
from app.repositories.execution import (
    BinanceOrderLedgerRepository,
    BinancePositionRepository,
    ExecutionFillRepository,
    ExecutionReconciliationEventRepository,
    OrderSubmissionRepository,
    PlanRepository,
)
from app.services.execution.safety import SafetyLockService

_CRITICAL = {ReconciliationSeverity.CRITICAL}
_HARD_LOCK_MISMATCHES = {
    "ORPHAN_POSITION_EXCHANGE": LockScopeType.SYMBOL,
    "MISSING_STOP_ORDER": LockScopeType.SYMBOL,
    "USER_STREAM_STALE": LockScopeType.GLOBAL,
    "FILL_EVENT_GAP": LockScopeType.SYMBOL,
}


@dataclass(slots=True)
class ReconciliationResult:
    symbol: str
    mismatches: list[dict[str, Any]]
    highest_severity: ReconciliationSeverity
    lock_required: bool
    auto_resolve_requested: bool
    auto_resolve_applied: bool
    apply_lock_requested: bool
    events_recorded: int
    generated_at: datetime


class ExecutionReconciliationService:
    USER_STREAM_STALE_SECONDS = 15 * 60

    def __init__(
        self,
        *,
        plan_repo: PlanRepository,
        submission_repo: OrderSubmissionRepository,
        binance_order_repo: BinanceOrderLedgerRepository,
        binance_position_repo: BinancePositionRepository,
        fill_repo: ExecutionFillRepository,
        event_repo: ExecutionReconciliationEventRepository,
        safety_locks: SafetyLockService,
        settings: Settings | None = None,
    ):
        self.plan_repo = plan_repo
        self.submission_repo = submission_repo
        self.binance_order_repo = binance_order_repo
        self.binance_position_repo = binance_position_repo
        self.fill_repo = fill_repo
        self.event_repo = event_repo
        self.safety_locks = safety_locks
        self.settings = settings or get_settings()

    def _local_open_plans(self, symbol: str) -> list[Plan]:
        stmt = (
            select(Plan)
            .where(
                Plan.symbol == symbol.upper(),
                Plan.state.in_([PlanState.ENTERED.value, PlanState.PARTIAL_EXIT.value]),
            )
            .order_by(Plan.valid_from.desc())
        )
        return list(self.plan_repo.db.scalars(stmt))

    def _latest_fill_for_plan(self, plan: Plan) -> Any | None:
        fills = self.fill_repo.list_for_plans(plan_ids=[str(plan.plan_id)], symbol=str(plan.symbol))
        if not fills:
            return None
        min_ts = datetime.min.replace(tzinfo=timezone.utc)
        return max(
            fills,
            key=lambda row: (
                self._utc(row.fill_ts) or min_ts,
                self._utc(getattr(row, "created_at", None)) or min_ts,
            ),
        )

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return int(parsed) if isfinite(parsed) else default

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

    @staticmethod
    def _severity_max(items: list[dict[str, Any]]) -> ReconciliationSeverity:
        ranking = {
            ReconciliationSeverity.INFO: 0,
            ReconciliationSeverity.WARNING: 1,
            ReconciliationSeverity.CRITICAL: 2,
        }
        highest = ReconciliationSeverity.INFO
        for item in items:
            severity = item["severity"]
            if ranking[severity] > ranking[highest]:
                highest = severity
        return highest

    @staticmethod
    def _mismatch(
        mismatch_type: str,
        severity: ReconciliationSeverity,
        message: str,
        *,
        local_snapshot: dict[str, Any] | None = None,
        exchange_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "mismatch_type": mismatch_type,
            "severity": severity,
            "message": message,
            "local_snapshot": dict(local_snapshot or {}),
            "exchange_snapshot": dict(exchange_snapshot or {}),
        }

    def _lock_scope_for(self, mismatch_type: str) -> LockScopeType | None:
        return _HARD_LOCK_MISMATCHES.get(mismatch_type)

    @staticmethod
    def _order_raw(row: Any) -> dict[str, Any]:
        raw = getattr(row, "raw", None)
        return raw if isinstance(raw, dict) else {}

    def _is_live_protection_row(self, row: Any) -> bool:
        raw = self._order_raw(row)
        return str(raw.get("order_purpose") or "").startswith("live_protection:")

    def _is_live_protection_order(self, row: Any, *, role: str) -> bool:
        raw = self._order_raw(row)
        purpose = str(raw.get("order_purpose") or "")
        order_type = str(row.order_type or "").upper()
        backed_by_exchange_close = self._safe_bool(row.reduce_only) or self._safe_bool(
            raw.get("close_position", raw.get("closePosition"))
        )
        if role == "stop":
            return "STOP" in order_type and (backed_by_exchange_close or purpose == "live_protection:stop_loss")
        if role == "tp":
            return (
                ("TAKE_PROFIT" in order_type or purpose.startswith("live_protection:tp"))
                and (backed_by_exchange_close or purpose.startswith("live_protection:tp"))
            )
        return False

    def _apply_lock_for(self, *, symbol: str, mismatch: dict[str, Any]) -> tuple[bool, str | None]:
        scope_type = self._lock_scope_for(mismatch["mismatch_type"])
        if scope_type is None:
            return False, None
        scope_key = symbol if scope_type == LockScopeType.SYMBOL else None
        self.safety_locks.set_lock(
            scope_type=scope_type,
            scope_key=scope_key,
            severity=LockSeverity.CRITICAL,
            reason_code=f"reconciliation_{str(mismatch['mismatch_type']).lower()}",
            reason_message=str(mismatch["message"]),
            allow_closes=True,
            metadata={
                "symbol": symbol,
                "mismatch_type": mismatch["mismatch_type"],
                "severity": mismatch["severity"].value,
            },
        )
        return True, scope_type.value

    def reconcile(
        self,
        *,
        symbol: str,
        auto_resolve: bool = False,
        apply_lock: bool = False,
    ) -> ReconciliationResult:
        normalized_symbol = symbol.upper()
        now = datetime.now(timezone.utc)
        mismatches: list[dict[str, Any]] = []

        local_orders = self.submission_repo.list_open(symbol=normalized_symbol)
        exchange_orders = self.binance_order_repo.list_open(symbol=normalized_symbol)
        local_by_client = {row.client_order_id: row for row in local_orders}
        exchange_by_client = {row.client_order_id: row for row in exchange_orders}

        for client_order_id, row in exchange_by_client.items():
            if client_order_id not in local_by_client:
                if self._is_live_protection_row(row):
                    continue
                mismatches.append(
                    self._mismatch(
                        "ORPHAN_ORDER_EXCHANGE",
                        ReconciliationSeverity.WARNING,
                        f"Exchange open order {client_order_id} has no local submission ledger entry.",
                        exchange_snapshot={"client_order_id": client_order_id, "status": row.status},
                    )
                )
        for client_order_id, row in local_by_client.items():
            if client_order_id not in exchange_by_client and row.requested_live:
                mismatches.append(
                    self._mismatch(
                        "ORPHAN_ORDER_LOCAL",
                        ReconciliationSeverity.WARNING,
                        f"Local open submission {client_order_id} is missing from exchange open orders.",
                        local_snapshot={"client_order_id": client_order_id, "state": row.state},
                    )
                )

        local_plans = self._local_open_plans(normalized_symbol)
        exchange_positions = self.binance_position_repo.list_open(symbol=normalized_symbol)
        auto_resolve_applied = False
        latest_fill_by_plan_id: dict[str, Any] = {str(plan.plan_id): self._latest_fill_for_plan(plan) for plan in local_plans}
        stale_closed_fill_plan_ids: set[str] = set()
        for plan in local_plans:
            latest_fill = latest_fill_by_plan_id.get(str(plan.plan_id))
            if str(getattr(latest_fill, "stage", "") or "") != ExecutionFillStage.CLOSED.value:
                continue
            stale_closed_fill_plan_ids.add(str(plan.plan_id))
            mismatches.append(
                self._mismatch(
                    "LOCAL_PLAN_STATE_STALE_AFTER_CLOSED_FILL",
                    ReconciliationSeverity.WARNING,
                    "Local plan state is open but its latest execution fill is CLOSED.",
                    local_snapshot={
                        "plan_id": plan.plan_id,
                        "state": plan.state,
                        "latest_fill_id": getattr(latest_fill, "fill_id", ""),
                        "latest_fill_stage": getattr(latest_fill, "stage", ""),
                        "latest_fill_to_state": getattr(latest_fill, "to_state", ""),
                    },
                    exchange_snapshot={"positions": []},
                )
            )
            if auto_resolve:
                plan.state = PlanState.CLOSED.value
                self.plan_repo.db.add(plan)
                auto_resolve_applied = True

        effective_local_plans = [plan for plan in local_plans if str(plan.plan_id) not in stale_closed_fill_plan_ids]
        if exchange_positions and not effective_local_plans:
            mismatches.append(
                self._mismatch(
                    "ORPHAN_POSITION_EXCHANGE",
                    ReconciliationSeverity.CRITICAL,
                    "Exchange reports an open position without a local open plan state.",
                    exchange_snapshot={
                        "positions": [
                            {"position_key": row.position_key, "position_amt": float(row.position_amt)}
                            for row in exchange_positions
                        ]
                    },
                )
            )
        if effective_local_plans and not exchange_positions:
            mismatches.append(
                self._mismatch(
                    "ORPHAN_POSITION_LOCAL",
                    ReconciliationSeverity.WARNING,
                    "Local plan state is open but the exchange position snapshot is flat.",
                    local_snapshot={
                        "open_plan_count": len(effective_local_plans),
                        "plan_ids": [row.plan_id for row in effective_local_plans],
                    },
                    exchange_snapshot={"positions": []},
                )
            )

        local_size_proxy = float(len(effective_local_plans))
        exchange_size = round(sum(abs(float(row.position_amt or 0.0)) for row in exchange_positions), 8)
        if effective_local_plans and exchange_positions and abs(local_size_proxy - exchange_size) > 1e-9:
            mismatches.append(
                self._mismatch(
                    "POSITION_SIZE_MISMATCH",
                    ReconciliationSeverity.CRITICAL,
                    "Local open position count proxy does not match the exchange position size snapshot.",
                    local_snapshot={"open_plan_count": local_size_proxy, "plan_ids": [row.plan_id for row in effective_local_plans]},
                    exchange_snapshot={"position_size": exchange_size},
                )
            )

        if exchange_positions:
            stop_present = any(self._is_live_protection_order(row, role="stop") for row in exchange_orders)
            tp_present = any(self._is_live_protection_order(row, role="tp") for row in exchange_orders)
            if not stop_present:
                mismatches.append(
                    self._mismatch(
                        "MISSING_STOP_ORDER",
                        ReconciliationSeverity.CRITICAL,
                        "Exchange position is open but no live stop protection order is present.",
                    )
                )
            if not tp_present:
                mismatches.append(
                    self._mismatch(
                        "MISSING_TP_ORDER",
                        ReconciliationSeverity.WARNING,
                        "Exchange position is open but no live take-profit protection order is present.",
                    )
                )

        submitted_plan_ids = sorted({row.plan_id for row in local_orders})
        if submitted_plan_ids:
            fills = self.fill_repo.list_for_plans(plan_ids=submitted_plan_ids, symbol=normalized_symbol)
            latest_submission_ts = max(
                (self._utc(row.submitted_at) for row in local_orders if row.submitted_at is not None),
                default=now,
            )
            if not fills and latest_submission_ts <= now - timedelta(minutes=5):
                mismatches.append(
                    self._mismatch(
                        "FILL_EVENT_GAP",
                        ReconciliationSeverity.CRITICAL,
                        "Open submissions exist but no execution fill event has been recorded recently.",
                        local_snapshot={"plan_ids": submitted_plan_ids},
                    )
                )

        latest_order_event = max(
            (self._utc(row.last_event_ts) for row in exchange_orders if row.last_event_ts is not None),
            default=None,
        )
        latest_position_event = max(
            (self._utc(row.update_ts) for row in exchange_positions if row.update_ts is not None),
            default=None,
        )
        latest_stream_event = max(filter(None, [latest_order_event, latest_position_event]), default=None)
        if (exchange_orders or exchange_positions) and (
            latest_stream_event is None
            or latest_stream_event
            <= now
            - timedelta(
                seconds=self._safe_int(
                    self.settings.auto_trading_reconciliation_user_stream_stale_seconds,
                    default=self.USER_STREAM_STALE_SECONDS,
                )
            )
        ):
            mismatches.append(
                self._mismatch(
                    "USER_STREAM_STALE",
                    ReconciliationSeverity.CRITICAL,
                    "Latest exchange order/position snapshot is stale relative to the user-stream freshness threshold.",
                    exchange_snapshot={
                        "latest_stream_event_ts": latest_stream_event.isoformat() if latest_stream_event is not None else None
                    },
                )
            )

        highest = self._severity_max(mismatches) if mismatches else ReconciliationSeverity.INFO
        lock_required = highest in _CRITICAL
        for mismatch in mismatches:
            should_apply_lock = bool(apply_lock) and self._lock_scope_for(mismatch["mismatch_type"]) is not None
            lock_applied = False
            lock_scope = None
            if should_apply_lock:
                lock_applied, lock_scope = self._apply_lock_for(symbol=normalized_symbol, mismatch=mismatch)
            self.event_repo.add(
                ExecutionReconciliationEvent(
                    event_id=f"recon_{uuid4().hex[:18]}",
                    symbol=normalized_symbol,
                    mismatch_type=mismatch["mismatch_type"],
                    severity=mismatch["severity"].value,
                    message=mismatch["message"],
                    local_snapshot=mismatch["local_snapshot"],
                    exchange_snapshot=mismatch["exchange_snapshot"],
                    payload={
                        "auto_resolve_requested": bool(auto_resolve),
                        "apply_lock_requested": bool(apply_lock),
                    },
                    lock_required=mismatch["mismatch_type"] in _HARD_LOCK_MISMATCHES or lock_required,
                    lock_applied=lock_applied,
                    lock_scope=lock_scope,
                )
            )

        return ReconciliationResult(
            symbol=normalized_symbol,
            mismatches=mismatches,
            highest_severity=highest,
            lock_required=lock_required,
            auto_resolve_requested=bool(auto_resolve),
            auto_resolve_applied=auto_resolve_applied,
            apply_lock_requested=bool(apply_lock),
            events_recorded=len(mismatches),
            generated_at=now,
        )
