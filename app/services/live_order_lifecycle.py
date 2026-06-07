from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.enums import ExecutionFillStage
from app.db.models import (
    BinanceOrderLedger,
    ExecutionFill,
    ExecutionReconciliationEvent,
    OrderIntent,
    OrderSubmission,
    Plan,
)


class LiveOrderLifecycleReporter:
    """Builds a compact audit trail from live intent through exchange/fill lifecycle."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return float(default)
        return parsed if isfinite(parsed) else float(default)

    @staticmethod
    def _safe_dict(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

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
    def _is_blank_detail(value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}

    @classmethod
    def _enrich_validation_block_detail(cls, detail: dict[str, Any]) -> dict[str, Any]:
        if not str(detail.get("candidate_block_reason") or "").strip():
            message = str(detail.get("candidate_block_reason_message") or "").strip()
            deployment_message = str(detail.get("deployment_message") or "").strip()
            if message and (message == deployment_message or message.upper().startswith("GO")):
                detail = dict(detail)
                detail.pop("candidate_block_reason_message", None)
        if detail.get("primary_cause") or detail.get("root_causes"):
            return detail
        grade = str(detail.get("grade") or "").upper()
        recommendation = str(detail.get("recommendation") or "").lower()
        if grade != "F" and recommendation != "do-not-deploy":
            return detail

        metrics = cls._safe_dict(detail.get("metrics"))
        sample_size = max(
            int(cls._safe_float(metrics.get("sample_size"))),
            int(cls._safe_float(metrics.get("trade_count"))),
            int(cls._safe_float(metrics.get("closed_trades"))),
        )
        win_rate = cls._safe_float(metrics.get("win_rate"))
        expectancy = cls._safe_float(metrics.get("expectancy_r"), default=cls._safe_float(metrics.get("ev"), default=cls._safe_float(metrics.get("ev_r"))))
        total_score = cls._safe_float(metrics.get("total_score"))

        root_causes: list[dict[str, Any]] = []

        def add(code: str, message: str) -> None:
            if code not in {item.get("code") for item in root_causes}:
                root_causes.append({"code": code, "message": message})

        if sample_size <= 0:
            add("validation_sample_missing", "No closed validation sample is available for this symbol/contract.")
        elif sample_size < 30:
            add("validation_sample_below_confidence_floor", "Validation sample is below the confidence floor.")
        if expectancy <= 0.0:
            add("validation_expectancy_non_positive", "Validation expectancy is not positive after costs.")
        if win_rate <= 0.0:
            add("validation_win_rate_missing_or_zero", "Validation win rate is missing or zero.")
        if grade == "F" or total_score < 45.0:
            add("validation_score_below_deploy_floor", "Validation score is below the do-not-deploy floor.")
        if str(detail.get("risk_state") or "") not in {"", "OPEN"}:
            add("risk_gate_not_open", "Runtime risk gate is not open.")
        if str(detail.get("candidate_block_reason") or ""):
            add("runtime_candidate_blocked", "Runtime candidate has a blocking reason.")
        if not root_causes:
            add("validation_recommendation_do_not_deploy", "Validation recommendation is do-not-deploy.")

        enriched = dict(detail)
        enriched["primary_cause"] = str(root_causes[0].get("code") or "validation_do_not_deploy")
        enriched["root_causes"] = root_causes[:8]
        return enriched

    @staticmethod
    def _iso(value: Any) -> str | None:
        return value.isoformat() if isinstance(value, datetime) else None

    @classmethod
    def _latency_ms(cls, start: Any, end: Any) -> float | None:
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            return None
        return round(max((cls._sort_ts(end) - cls._sort_ts(start)).total_seconds() * 1000.0, 0.0), 4)

    @staticmethod
    def _sort_ts(value: Any) -> datetime:
        if not isinstance(value, datetime):
            return datetime.min.replace(tzinfo=timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _normalize_families(value: list[str] | tuple[str, ...] | set[str] | None) -> set[str]:
        return {
            str(item or "").strip()
            for item in list(value or [])
            if str(item or "").strip()
        }

    @staticmethod
    def _normalize_symbols(value: list[str] | tuple[str, ...] | set[str] | None) -> set[str]:
        return {
            str(item or "").strip().upper()
            for item in list(value or [])
            if str(item or "").strip()
        }

    @classmethod
    def _blocked_intent_detail(cls, row: OrderIntent) -> dict[str, Any]:
        approval = cls._safe_dict(row.approval_snapshot)
        detail = cls._safe_dict(approval.get("validation_block_detail"))
        if not detail and str(row.decision_reason_code or "") == "validation_do_not_deploy":
            detail = {
                "recommendation": approval.get("validation_recommendation"),
                "grade": approval.get("validation_grade"),
                "risk_state": approval.get("risk_state"),
                "risk_reason": approval.get("risk_reason"),
                "deployment_code": approval.get("deployment_code"),
                "deployment_message": approval.get("deployment_message"),
                "candidate_block_reason": approval.get("block_reason"),
                "candidate_block_reason_message": approval.get("block_reason_message"),
            }
        if str(row.decision_reason_code or "") == "validation_do_not_deploy":
            detail = cls._enrich_validation_block_detail(detail)
        return {key: value for key, value in detail.items() if not cls._is_blank_detail(value)}

    @classmethod
    def _weighted_price(cls, fills: list[ExecutionFill]) -> float | None:
        qty = sum(max(cls._safe_float(fill.qty), 0.0) for fill in fills)
        if qty <= 0.0:
            return None
        notional = sum(max(cls._safe_float(fill.qty), 0.0) * cls._safe_float(fill.price) for fill in fills)
        return notional / qty

    @classmethod
    def _entry_slippage_bps(cls, *, plan: Plan | None, entry_price: float | None) -> float | None:
        if plan is None or entry_price is None:
            return None
        target = cls._safe_float(plan.entry_price)
        if target <= 0.0:
            return None
        direction = str(plan.direction or "").lower()
        if direction == "short":
            return (target - entry_price) / target * 10_000.0
        return (entry_price - target) / target * 10_000.0

    @classmethod
    def _exit_slippage_bps(
        cls,
        *,
        plan: Plan | None,
        exit_price: float | None,
        exit_source_event: dict[str, Any],
    ) -> float | None:
        if plan is None or exit_price is None:
            return None
        target = cls._safe_float(exit_source_event.get("price"))
        if target <= 0.0:
            return None
        direction = str(plan.direction or "").lower()
        if direction == "short":
            return (exit_price - target) / target * 10_000.0
        return (target - exit_price) / target * 10_000.0

    @classmethod
    def _computed_realized_r(
        cls,
        *,
        plan: Plan | None,
        entry_price: float | None,
        exit_price: float | None,
    ) -> float | None:
        if plan is None or entry_price is None or exit_price is None:
            return None
        risk_abs = abs(cls._safe_float(plan.entry_price) - cls._safe_float(plan.sl))
        if risk_abs <= 0.0:
            return None
        direction = str(plan.direction or "").lower()
        if direction == "short":
            return (entry_price - exit_price) / risk_abs
        return (exit_price - entry_price) / risk_abs

    @classmethod
    def _payload_realized_r(cls, fills: list[ExecutionFill]) -> float | None:
        for fill in reversed(fills):
            payload = cls._safe_dict(fill.payload)
            value = payload.get("realized_r")
            if value not in {None, ""}:
                return cls._safe_float(value)
        return None

    @classmethod
    def _exit_reason(cls, fills: list[ExecutionFill], plan: Plan | None) -> str:
        for fill in reversed(fills):
            reason = cls._safe_dict(fill.payload).get("exit_reason")
            if reason:
                return str(reason)
        if plan is not None:
            reason = cls._safe_dict(plan.validity).get("final_exit_reason")
            if reason:
                return str(reason)
        return ""

    @staticmethod
    def _terminal_submission_state(state: str) -> bool:
        return str(state or "").upper() in {"FILLED", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED"}

    @classmethod
    def _fill_matches_submission(cls, *, fill: ExecutionFill, submission: OrderSubmission) -> bool:
        payload = cls._safe_dict(fill.payload)
        client_order_id = str(payload.get("client_order_id") or "").strip()
        exchange_order_id = str(payload.get("exchange_order_id") or "").strip()
        submission_client_order_id = str(submission.client_order_id or "").strip()
        submission_exchange_order_id = str(submission.exchange_order_id or "").strip()
        if submission_client_order_id and client_order_id == submission_client_order_id:
            return True
        if submission_exchange_order_id and exchange_order_id == submission_exchange_order_id:
            return True
        return False

    @classmethod
    def _fills_for_submission(
        cls,
        *,
        submission: OrderSubmission,
        plan_fills: list[ExecutionFill],
    ) -> tuple[list[ExecutionFill], list[ExecutionFill], list[ExecutionFill]]:
        entry_fills = [
            fill
            for fill in plan_fills
            if str(fill.stage) == ExecutionFillStage.ENTRY.value
            and cls._fill_matches_submission(fill=fill, submission=submission)
        ]
        if not entry_fills:
            return [], [], []

        first_entry_ts = min(cls._sort_ts(fill.fill_ts or fill.created_at) for fill in entry_fills)
        exit_fills = [
            fill
            for fill in plan_fills
            if str(fill.stage) in {ExecutionFillStage.PARTIAL_EXIT.value, ExecutionFillStage.CLOSED.value}
            and cls._sort_ts(fill.fill_ts or fill.created_at) >= first_entry_ts
        ]
        closed_fills = [fill for fill in exit_fills if str(fill.stage) == ExecutionFillStage.CLOSED.value]
        return entry_fills, exit_fills, closed_fills

    @classmethod
    def _lifecycle_status(
        cls,
        *,
        submission: OrderSubmission,
        entry_fills: list[ExecutionFill],
        closed_fills: list[ExecutionFill],
        exchange_flat_after_entry: bool = False,
    ) -> str:
        state = str(submission.state or "").upper()
        submit_status = str(submission.submit_status or "").upper()
        if closed_fills:
            return "closed"
        if exchange_flat_after_entry and entry_fills:
            return "exchange_flat_after_entry"
        if entry_fills:
            return "open_after_entry"
        if state in {"REJECTED", "CANCELLED", "CANCELED"} or "ERROR" in submit_status:
            return "rejected_or_error"
        if cls._terminal_submission_state(state):
            return "terminal_without_entry_fill"
        return "submitted_without_entry_fill"

    @classmethod
    def _flat_reconciliation_by_plan(
        cls,
        reconciliation_events: list[ExecutionReconciliationEvent],
    ) -> dict[str, ExecutionReconciliationEvent]:
        by_plan: dict[str, ExecutionReconciliationEvent] = {}
        for event in sorted(reconciliation_events, key=lambda row: cls._sort_ts(row.created_at)):
            local_snapshot = cls._safe_dict(event.local_snapshot)
            for plan_id in list(local_snapshot.get("plan_ids") or []):
                normalized = str(plan_id or "").strip()
                if normalized:
                    by_plan[normalized] = event
        return by_plan

    def _intent_counts(
        self,
        *,
        cutoff: datetime,
        symbol: str | None,
        live_only: bool,
        symbols: list[str] | tuple[str, ...] | set[str] | None = None,
        strategy_families: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> dict[str, Any]:
        stmt = select(OrderIntent).where(OrderIntent.created_at >= cutoff)
        if symbol:
            stmt = stmt.where(OrderIntent.symbol == symbol.upper())
        else:
            symbol_filter = self._normalize_symbols(symbols)
            if symbol_filter:
                stmt = stmt.where(OrderIntent.symbol.in_(sorted(symbol_filter)))
        if live_only:
            stmt = stmt.where(OrderIntent.execution_mode.in_(("MICRO_LIVE", "LIVE")))
        family_filter = self._normalize_families(strategy_families)
        if family_filter:
            stmt = stmt.where(OrderIntent.strategy_family.in_(sorted(family_filter)))
        intents = list(self.db.scalars(stmt))
        reason_counts = Counter(str(row.decision_reason_code or "") or "none" for row in intents)
        mode_counts = Counter(str(row.execution_mode or "") or "unknown" for row in intents)
        approval_counts = Counter(str(row.approval_state or "") or "unknown" for row in intents)
        decision_counts = Counter(str(row.submit_decision or "") or "unknown" for row in intents)
        plan_counts = Counter(str(row.plan_id or "") or "none" for row in intents)
        duplicate_plan_counts = {
            plan_id: count
            for plan_id, count in plan_counts.most_common(10)
            if count > 1
        }
        recent_blocked = sorted(
            (row for row in intents if str(row.approval_state or "") == "BLOCKED" or str(row.submit_decision or "").startswith("SKIP")),
            key=lambda row: self._sort_ts(row.created_at),
            reverse=True,
        )[:10]
        return {
            "total": len(intents),
            "distinct_plan_count": len(plan_counts),
            "duplicate_plan_intent_count": sum(count - 1 for count in plan_counts.values() if count > 1),
            "top_duplicate_plan_ids": duplicate_plan_counts,
            "submit_ready": sum(1 for row in intents if str(row.submit_decision) == "SUBMIT"),
            "blocked": sum(1 for row in intents if str(row.approval_state) == "BLOCKED"),
            "by_mode": dict(sorted(mode_counts.items())),
            "by_approval": dict(sorted(approval_counts.items())),
            "by_decision": dict(sorted(decision_counts.items())),
            "family_filter": sorted(family_filter),
            "top_block_reasons": dict(reason_counts.most_common(10)),
            "recent_blocked_intents": [
                {
                    "intent_id": row.intent_id,
                    "plan_id": row.plan_id,
                    "symbol": row.symbol,
                    "strategy_family": row.strategy_family,
                    "approval_state": row.approval_state,
                    "submit_decision": row.submit_decision,
                    "decision_reason_code": row.decision_reason_code,
                    "decision_reason_message": row.decision_reason_message,
                    "block_detail": self._blocked_intent_detail(row),
                    "created_at": self._iso(row.created_at),
                }
                for row in recent_blocked
            ],
        }

    def generate(
        self,
        *,
        days: int = 30,
        symbol: str | None = None,
        symbols: list[str] | tuple[str, ...] | set[str] | None = None,
        live_only: bool = True,
        limit: int = 100,
        generated_at: datetime | None = None,
        start_at: datetime | None = None,
        strategy_families: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> dict[str, Any]:
        now = generated_at or datetime.now(timezone.utc)
        cutoff = self._sort_ts(start_at) if start_at is not None else now - timedelta(days=max(1, int(days)))
        stmt = select(OrderSubmission).where(OrderSubmission.submitted_at >= cutoff)
        if symbol:
            stmt = stmt.where(OrderSubmission.symbol == symbol.upper())
        else:
            symbol_filter = self._normalize_symbols(symbols)
            if symbol_filter:
                stmt = stmt.where(OrderSubmission.symbol.in_(sorted(symbol_filter)))
        if live_only:
            stmt = stmt.where(OrderSubmission.requested_live.is_(True))
        stmt = stmt.order_by(desc(OrderSubmission.submitted_at), desc(OrderSubmission.updated_at)).limit(max(1, int(limit)))
        submissions = list(self.db.scalars(stmt))

        intent_ids = [row.intent_id for row in submissions]
        intents = {
            row.intent_id: row
            for row in self.db.scalars(select(OrderIntent).where(OrderIntent.intent_id.in_(intent_ids))).all()
        } if intent_ids else {}
        family_filter = self._normalize_families(strategy_families)
        if family_filter:
            submissions = [
                row
                for row in submissions
                if str(getattr(intents.get(row.intent_id), "strategy_family", "") or "") in family_filter
            ]
        plan_ids = [row.plan_id for row in submissions]
        client_order_ids = [row.client_order_id for row in submissions]
        plans = {
            row.plan_id: row
            for row in self.db.scalars(select(Plan).where(Plan.plan_id.in_(plan_ids))).all()
        } if plan_ids else {}
        fill_rows = (
            list(
                self.db.scalars(
                    select(ExecutionFill)
                    .where(ExecutionFill.plan_id.in_(plan_ids))
                    .order_by(ExecutionFill.fill_ts.asc(), ExecutionFill.created_at.asc())
                )
            )
            if plan_ids
            else []
        )
        fills_by_plan: dict[str, list[ExecutionFill]] = defaultdict(list)
        for fill in fill_rows:
            fills_by_plan[fill.plan_id].append(fill)
        submission_symbols = sorted({str(row.symbol or "").upper() for row in submissions if str(row.symbol or "").strip()})
        reconciliation_rows = (
            list(
                self.db.scalars(
                    select(ExecutionReconciliationEvent)
                    .where(ExecutionReconciliationEvent.created_at >= cutoff)
                    .where(ExecutionReconciliationEvent.mismatch_type == "ORPHAN_POSITION_LOCAL")
                    .where(ExecutionReconciliationEvent.symbol.in_(submission_symbols))
                    .order_by(ExecutionReconciliationEvent.created_at.asc())
                )
            )
            if submission_symbols
            else []
        )
        flat_reconciliation_by_plan = self._flat_reconciliation_by_plan(reconciliation_rows)
        ledger_rows = (
            list(
                self.db.scalars(
                    select(BinanceOrderLedger).where(BinanceOrderLedger.client_order_id.in_(client_order_ids))
                )
            )
            if client_order_ids
            else []
        )
        ledgers_by_client_order_id = {row.client_order_id: row for row in ledger_rows}

        rows: list[dict[str, Any]] = []
        slippage_values: list[float] = []
        exit_slippage_values: list[float] = []
        realized_values: list[float] = []
        total_fee = 0.0
        status_counts: Counter[str] = Counter()
        symbol_counts: Counter[str] = Counter()

        for submission in submissions:
            intent = intents.get(submission.intent_id)
            plan = plans.get(submission.plan_id)
            plan_fills = fills_by_plan.get(submission.plan_id, [])
            entry_fills, exit_fills, closed_fills = self._fills_for_submission(
                submission=submission,
                plan_fills=plan_fills,
            )
            entry_price = self._weighted_price(entry_fills)
            exit_price = self._weighted_price(exit_fills)
            slippage_bps = self._entry_slippage_bps(plan=plan, entry_price=entry_price)
            payload_realized_r = self._payload_realized_r(closed_fills or exit_fills)
            computed_realized_r = self._computed_realized_r(plan=plan, entry_price=entry_price, exit_price=exit_price)
            realized_r = payload_realized_r if payload_realized_r is not None else computed_realized_r
            fee_total = sum(self._safe_float(fill.fee) for fill in entry_fills + exit_fills)
            flat_reconciliation = flat_reconciliation_by_plan.get(submission.plan_id)
            latest_entry_ts = max((self._sort_ts(fill.fill_ts or fill.created_at) for fill in entry_fills), default=None)
            first_entry_ts = min((self._sort_ts(fill.fill_ts or fill.created_at) for fill in entry_fills), default=None)
            latest_exit_ts = max((self._sort_ts(fill.fill_ts or fill.created_at) for fill in exit_fills), default=None)
            exchange_flat_after_entry = (
                flat_reconciliation is not None
                and latest_entry_ts is not None
                and self._sort_ts(flat_reconciliation.created_at) >= latest_entry_ts
            )
            reconciliation_event = flat_reconciliation if exchange_flat_after_entry else None
            lifecycle_status = self._lifecycle_status(
                submission=submission,
                entry_fills=entry_fills,
                closed_fills=closed_fills,
                exchange_flat_after_entry=exchange_flat_after_entry,
            )
            ledger = ledgers_by_client_order_id.get(submission.client_order_id)
            plan_validity = self._safe_dict(getattr(plan, "validity", {}) if plan is not None else {})
            plan_source_event = self._safe_dict(plan_validity.get("source_event"))
            exit_source_event: dict[str, Any] = {}
            for fill in reversed(exit_fills):
                payload = self._safe_dict(fill.payload)
                candidate_event = self._safe_dict(payload.get("source_event"))
                if candidate_event:
                    exit_source_event = candidate_event
                    break
            exit_slippage_bps = self._exit_slippage_bps(
                plan=plan,
                exit_price=exit_price,
                exit_source_event=exit_source_event,
            )
            entry_fill_qty = sum(max(self._safe_float(fill.qty), 0.0) for fill in entry_fills)
            exit_fill_qty = sum(max(self._safe_float(fill.qty), 0.0) for fill in exit_fills)

            if slippage_bps is not None:
                slippage_values.append(float(slippage_bps))
            if exit_slippage_bps is not None:
                exit_slippage_values.append(float(exit_slippage_bps))
            if realized_r is not None:
                realized_values.append(float(realized_r))
            total_fee += fee_total
            status_counts[lifecycle_status] += 1
            symbol_counts[submission.symbol] += 1

            rows.append(
                {
                    "symbol": submission.symbol,
                    "plan_id": submission.plan_id,
                    "intent_id": submission.intent_id,
                    "submission_id": submission.submission_id,
                    "client_order_id": submission.client_order_id,
                    "exchange_order_id": submission.exchange_order_id,
                    "strategy_family": str(getattr(intent, "strategy_family", "") or ""),
                    "execution_mode": str(getattr(intent, "execution_mode", submission.execution_mode) or ""),
                    "approval_state": str(getattr(intent, "approval_state", "") or ""),
                    "submit_decision": str(getattr(intent, "submit_decision", "") or ""),
                    "decision_reason_code": str(getattr(intent, "decision_reason_code", "") or ""),
                    "requested_live": self._safe_bool(submission.requested_live),
                    "adapter": submission.adapter,
                    "state": submission.state,
                    "submit_status": submission.submit_status,
                    "message": submission.message,
                    "side": submission.side,
                    "order_type": submission.order_type,
                    "submitted_at": self._iso(submission.submitted_at),
                    "acknowledged_at": self._iso(submission.acknowledged_at),
                    "entry_first_fill_at": self._iso(first_entry_ts),
                    "entry_last_fill_at": self._iso(latest_entry_ts),
                    "exit_last_fill_at": self._iso(latest_exit_ts),
                    "ack_latency_ms": self._latency_ms(submission.submitted_at, submission.acknowledged_at),
                    "fill_latency_ms": self._latency_ms(submission.submitted_at, first_entry_ts),
                    "plan_direction": str(getattr(plan, "direction", "") or ""),
                    "plan_entry_price": self._safe_float(getattr(plan, "entry_price", 0.0)) if plan else None,
                    "plan_stop_price": self._safe_float(getattr(plan, "sl", 0.0)) if plan else None,
                    "plan_source_event": plan_source_event,
                    "plan_source_event_key": str(plan_validity.get("source_event_key") or ""),
                    "plan_source_event_ts": str(plan_validity.get("source_event_ts") or ""),
                    "plan_source_model_id": str(plan_validity.get("source_model_id") or ""),
                    "exit_source_event": exit_source_event,
                    "entry_fill_count": len(entry_fills),
                    "exit_fill_count": len(exit_fills),
                    "closed_fill_count": len(closed_fills),
                    "entry_fill_qty": round(entry_fill_qty, 8),
                    "exit_fill_qty": round(exit_fill_qty, 8),
                    "entry_avg_price": round(entry_price, 8) if entry_price is not None else None,
                    "exit_avg_price": round(exit_price, 8) if exit_price is not None else None,
                    "entry_slippage_bps": round(slippage_bps, 4) if slippage_bps is not None else None,
                    "exit_slippage_bps": round(exit_slippage_bps, 4) if exit_slippage_bps is not None else None,
                    "realized_r": round(realized_r, 4) if realized_r is not None else None,
                    "exit_reason": self._exit_reason(closed_fills or exit_fills, plan),
                    "fee_total": round(fee_total, 8),
                    "lifecycle_status": lifecycle_status,
                    "exchange_flat_after_entry": exchange_flat_after_entry,
                    "reconciliation_event_id": str(getattr(reconciliation_event, "event_id", "") or ""),
                    "reconciliation_mismatch_type": str(getattr(reconciliation_event, "mismatch_type", "") or ""),
                    "reconciliation_created_at": self._iso(getattr(reconciliation_event, "created_at", None)),
                    "binance_ledger_status": str(getattr(ledger, "status", "") or ""),
                    "binance_order_price": self._safe_float(getattr(ledger, "price", 0.0)) if ledger else None,
                    "binance_orig_qty": self._safe_float(getattr(ledger, "orig_qty", 0.0)) if ledger else None,
                    "binance_executed_qty": self._safe_float(getattr(ledger, "executed_qty", 0.0)) if ledger else None,
                    "binance_live_enabled": self._safe_bool(getattr(ledger, "live_enabled", False)) if ledger else None,
                    "binance_test_order": self._safe_bool(getattr(ledger, "test_order", False)) if ledger else None,
                }
            )

        return {
            "generated_at": now.isoformat(),
            "window_start": cutoff.isoformat(),
            "window_days": max(1, int(days)),
            "symbol": symbol.upper() if symbol else "",
            "symbols": sorted(self._normalize_symbols(symbols)) if not symbol else [symbol.upper()],
            "live_only": self._safe_bool(live_only),
            "summary": {
                "submission_count": len(submissions),
                "requested_live_count": sum(1 for row in submissions if self._safe_bool(row.requested_live)),
                "entry_fill_count": sum(int(row["entry_fill_count"]) for row in rows),
                "closed_count": int(status_counts.get("closed", 0)),
                "open_after_entry_count": int(status_counts.get("open_after_entry", 0)),
                "exchange_flat_after_entry_count": int(status_counts.get("exchange_flat_after_entry", 0)),
                "submitted_without_entry_fill_count": int(status_counts.get("submitted_without_entry_fill", 0)),
                "rejected_or_error_count": int(status_counts.get("rejected_or_error", 0)),
                "total_fee": round(total_fee, 8),
                "avg_entry_slippage_bps": round(sum(slippage_values) / len(slippage_values), 4) if slippage_values else None,
                "avg_exit_slippage_bps": (
                    round(sum(exit_slippage_values) / len(exit_slippage_values), 4)
                    if exit_slippage_values
                    else None
                ),
                "avg_realized_r": round(sum(realized_values) / len(realized_values), 4) if realized_values else None,
                "by_lifecycle_status": dict(sorted(status_counts.items())),
                "by_symbol": dict(symbol_counts.most_common()),
                "live_intents": self._intent_counts(
                    cutoff=cutoff,
                    symbol=symbol,
                    symbols=symbols,
                    live_only=self._safe_bool(live_only),
                    strategy_families=family_filter,
                ),
            },
            "rows": rows,
        }
