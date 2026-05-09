from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar

from app.core.enums import ExitReason, ExecutionFillStage
from app.db.models import ExecutionFill, Plan

TARGET_EXIT_REASONS = {
    ExitReason.TARGET_TP1.value,
    ExitReason.TARGET_TP2.value,
    ExitReason.TARGET_TP3.value,
}
FORCED_EXIT_REASONS = {
    ExitReason.STOP_LOSS.value,
    ExitReason.STRUCTURE_FAILURE.value,
    ExitReason.TIME_FAILURE.value,
    ExitReason.INFORMATION_FAILURE.value,
    ExitReason.MANUAL_FLATTEN.value,
    ExitReason.RISK_LOCK_FLATTEN.value,
    ExitReason.SESSION_END_FLATTEN.value,
}


@dataclass(slots=True)
class ExitEvaluation:
    exit_reason: str | None
    metadata: dict[str, Any]


class ExitEngineService:
    _explicit_reason_tokens: ClassVar[dict[str, ExitReason]] = {
        "risk_lock": ExitReason.RISK_LOCK_FLATTEN,
        "risk_lock_flatten": ExitReason.RISK_LOCK_FLATTEN,
        "session_end": ExitReason.SESSION_END_FLATTEN,
        "session_end_flatten": ExitReason.SESSION_END_FLATTEN,
        "manual": ExitReason.MANUAL_FLATTEN,
        "manual_flatten": ExitReason.MANUAL_FLATTEN,
        "structure_failure": ExitReason.STRUCTURE_FAILURE,
        "broken_level": ExitReason.STRUCTURE_FAILURE,
        "protected": ExitReason.STRUCTURE_FAILURE,
        "stop_loss": ExitReason.STOP_LOSS,
        "stop": ExitReason.STOP_LOSS,
        "time_failure": ExitReason.TIME_FAILURE,
        "information_failure": ExitReason.INFORMATION_FAILURE,
    }
    _leg_map: ClassVar[dict[str, ExitReason]] = {
        "tp1": ExitReason.TARGET_TP1,
        "tp2": ExitReason.TARGET_TP2,
        "tp3": ExitReason.TARGET_TP3,
        "runner": ExitReason.TARGET_TP3,
    }

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _coerce_exit_reason(value: Any) -> ExitReason | None:
        if value is None:
            return None
        if isinstance(value, ExitReason):
            return value
        try:
            return ExitReason(str(value))
        except ValueError:
            return None

    @staticmethod
    def _bar_seconds(timeframe: str) -> int:
        if timeframe == "15m":
            return 15 * 60
        return 5 * 60

    def _held_bars(self, *, plan: Plan, fill_ts: datetime, fills: list[ExecutionFill]) -> int:
        entry_ts = self._utc(plan.valid_from)
        for fill in fills:
            if str(fill.stage) == ExecutionFillStage.ENTRY.value:
                entry_ts = self._utc(fill.fill_ts)
                break
        delta = max(0.0, (self._utc(fill_ts) - entry_ts).total_seconds())
        bar_seconds = max(1, self._bar_seconds(str(plan.timeframe or "5m")))
        return int(math.ceil(delta / bar_seconds)) if delta > 0 else 0

    @staticmethod
    def _realized_r(*, plan: Plan, price: float) -> float:
        risk = abs(float(plan.entry_price) - float(plan.sl))
        if risk <= 1e-9:
            return 0.0
        if str(plan.direction).lower() == "short":
            return float((float(plan.entry_price) - float(price)) / risk)
        return float((float(price) - float(plan.entry_price)) / risk)

    @staticmethod
    def _price_tolerance(value: float) -> float:
        return max(abs(float(value)) * 0.0005, 1e-6)

    def _target_reason_from_price(self, *, plan: Plan, price: float) -> ExitReason | None:
        direction = str(plan.direction).lower()
        if direction == "short":
            if price <= float(plan.tp3) + self._price_tolerance(plan.tp3):
                return ExitReason.TARGET_TP3
            if price <= float(plan.tp2) + self._price_tolerance(plan.tp2):
                return ExitReason.TARGET_TP2
            if price <= float(plan.tp1) + self._price_tolerance(plan.tp1):
                return ExitReason.TARGET_TP1
            return None
        if price >= float(plan.tp3) - self._price_tolerance(plan.tp3):
            return ExitReason.TARGET_TP3
        if price >= float(plan.tp2) - self._price_tolerance(plan.tp2):
            return ExitReason.TARGET_TP2
        if price >= float(plan.tp1) - self._price_tolerance(plan.tp1):
            return ExitReason.TARGET_TP1
        return None

    def _stop_loss_hit(self, *, plan: Plan, price: float) -> bool:
        if str(plan.direction).lower() == "short":
            return price >= float(plan.sl) - self._price_tolerance(plan.sl)
        return price <= float(plan.sl) + self._price_tolerance(plan.sl)

    @staticmethod
    def _classification_flip_to_information_failure(before: str, after: str) -> bool:
        before_norm = str(before or "").lower()
        after_norm = str(after or "").lower()
        if not before_norm.startswith("rejection"):
            return False
        return after_norm.startswith("acceptance") or after_norm == "mixed"

    def _reason_from_payload(self, payload: dict[str, Any]) -> ExitReason | None:
        explicit = self._coerce_exit_reason(payload.get("exit_reason"))
        if explicit is not None:
            return explicit

        values: list[str] = []
        for key in (
            "reason",
            "status",
            "result",
            "error",
            "cancel_reason",
            "leg",
            "note",
            "notes",
        ):
            value = payload.get(key)
            if value is not None:
                values.append(str(value).lower())
        text = " ".join(values)
        for token, reason in self._explicit_reason_tokens.items():
            if token in text:
                return reason
        leg = str(payload.get("leg") or "").lower()
        return self._leg_map.get(leg)

    def _progress_to_target_pct(self, *, plan: Plan, price: float) -> float:
        entry = float(plan.entry_price)
        target = float(plan.tp2)
        if str(plan.direction).lower() == "short":
            distance = entry - target
            progress = entry - price
        else:
            distance = target - entry
            progress = price - entry
        if abs(distance) <= 1e-9:
            return 0.0
        return round(float((progress / distance) * 100.0), 2)

    def evaluate(
        self,
        *,
        plan: Plan,
        stage: ExecutionFillStage,
        fill_ts: datetime,
        price: float,
        fee: float,
        payload: dict[str, Any] | None,
        previous_fills: list[ExecutionFill],
    ) -> ExitEvaluation:
        metadata = dict(payload or {})
        if stage not in {ExecutionFillStage.PARTIAL_EXIT, ExecutionFillStage.CLOSED}:
            return ExitEvaluation(exit_reason=None, metadata=metadata)

        validity = dict(plan.validity or {})
        strategy_family = str(metadata.get("strategy_family") or validity.get("strategy_family") or "legacy_zone_plan")
        classification_before = str(
            metadata.get("classification_before_exit")
            or validity.get("reaction_classification")
            or "not_available"
        )
        classification_after = str(
            metadata.get("classification_after_exit")
            or metadata.get("classification_after")
            or classification_before
        )
        held_bars = int(metadata.get("held_bars") or self._held_bars(plan=plan, fill_ts=fill_ts, fills=previous_fills))
        remaining_qty_raw = metadata.get("remaining_qty")
        remaining_qty = None if remaining_qty_raw is None else float(remaining_qty_raw)
        if stage == ExecutionFillStage.CLOSED and remaining_qty is None:
            remaining_qty = 0.0

        realized_r_raw = metadata.get("realized_r")
        realized_r = float(realized_r_raw) if realized_r_raw is not None else self._realized_r(plan=plan, price=price)

        max_allowed_bars = int(validity.get("strategy_family_time_stop_max_bars", 0) or 0)
        exit_reason = self._reason_from_payload(metadata)
        if exit_reason is None:
            if stage == ExecutionFillStage.PARTIAL_EXIT:
                exit_reason = self._target_reason_from_price(plan=plan, price=price) or ExitReason.TARGET_TP1
            elif self._classification_flip_to_information_failure(classification_before, classification_after):
                exit_reason = ExitReason.INFORMATION_FAILURE
            elif self._stop_loss_hit(plan=plan, price=price):
                exit_reason = ExitReason.STOP_LOSS
            elif max_allowed_bars > 0 and held_bars > max_allowed_bars:
                exit_reason = ExitReason.TIME_FAILURE
            else:
                exit_reason = self._target_reason_from_price(plan=plan, price=price) or ExitReason.MANUAL_FLATTEN

        trigger_detail = dict(metadata.get("trigger_detail") or {})
        if exit_reason == ExitReason.TIME_FAILURE:
            trigger_detail.setdefault("max_allowed_bars", max_allowed_bars)
            trigger_detail.setdefault("actual_held_bars", held_bars)
            trigger_detail.setdefault("progress_to_target_pct", self._progress_to_target_pct(plan=plan, price=price))
        if exit_reason == ExitReason.INFORMATION_FAILURE:
            trigger_detail.setdefault("old_classification", classification_before)
            trigger_detail.setdefault("new_classification", classification_after)
            trigger_detail.setdefault("narrative_invalidated", True)
            if "mixed" in classification_after.lower() and "mixed_score" not in trigger_detail:
                mixed_score = metadata.get("mixed_score")
                if mixed_score is not None:
                    trigger_detail["mixed_score"] = float(mixed_score)

        metadata.update(
            {
                "strategy_family": strategy_family,
                "exit_reason": exit_reason.value,
                "exit_ts": str(metadata.get("exit_ts") or self._utc(fill_ts).isoformat()),
                "exit_price": float(metadata.get("exit_price") or price),
                "remaining_qty": remaining_qty,
                "realized_r": round(realized_r, 4),
                "held_bars": held_bars,
                "classification_before_exit": classification_before,
                "classification_after_exit": classification_after,
                "trigger_detail": trigger_detail,
            }
        )
        metadata.setdefault("fees", float(metadata.get("fees") or fee))
        return ExitEvaluation(exit_reason=exit_reason.value, metadata=metadata)
