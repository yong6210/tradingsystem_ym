from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from app.core.enums import ExecutionFillStage, PlanState
from app.db.models import ExecutionFill
from app.db.repositories import ExecutionFillRepository, PlanRepository
from app.services.exit_engine import ExitEngineService
from app.services.lane_tracker import get_execution_lane_tracker


@dataclass(slots=True)
class FillApplyInput:
    fill_id: str
    plan_id: str
    symbol: str
    stage: ExecutionFillStage
    fill_ts: datetime
    price: float
    qty: float
    fee: float = 0.0
    payload: dict[str, Any] | None = None


@dataclass(slots=True)
class FillApplyResult:
    accepted: bool
    duplicate: bool
    fill_id: str
    plan_id: str | None
    symbol: str | None
    stage: str | None
    from_state: str | None
    to_state: str | None
    state_changed: bool
    reason: str
    exit_reason: str | None = None


class PositionStateMachineService:
    _stage_to_state: ClassVar[dict[ExecutionFillStage, PlanState]] = {
        ExecutionFillStage.TRIGGERED: PlanState.TRIGGERED,
        ExecutionFillStage.ENTRY: PlanState.ENTERED,
        ExecutionFillStage.PARTIAL_EXIT: PlanState.PARTIAL_EXIT,
        ExecutionFillStage.CLOSED: PlanState.CLOSED,
    }

    _state_rank: ClassVar[dict[PlanState, int]] = {
        PlanState.PLANNED: 0,
        PlanState.ARMED: 0,
        PlanState.TRIGGERED: 1,
        PlanState.ENTERED: 2,
        PlanState.PARTIAL_EXIT: 3,
        PlanState.CLOSED: 4,
    }

    def __init__(
        self,
        *,
        plan_repo: PlanRepository,
        fill_repo: ExecutionFillRepository,
        strategy_version: str,
    ):
        self.plan_repo = plan_repo
        self.fill_repo = fill_repo
        self.strategy_version = strategy_version
        self.exit_engine = ExitEngineService()

    def apply(self, data: FillApplyInput) -> FillApplyResult:
        existing = self.fill_repo.get(data.fill_id)
        if existing is not None:
            return FillApplyResult(
                accepted=True,
                duplicate=True,
                fill_id=existing.fill_id,
                plan_id=existing.plan_id,
                symbol=existing.symbol,
                stage=existing.stage,
                from_state=existing.from_state,
                to_state=existing.to_state,
                state_changed=bool(existing.state_changed),
                reason="duplicate_fill_id",
                exit_reason=dict(existing.payload or {}).get("exit_reason"),
            )

        plan = self.plan_repo.get(data.plan_id)
        if plan is None:
            return FillApplyResult(
                accepted=False,
                duplicate=False,
                fill_id=data.fill_id,
                plan_id=None,
                symbol=data.symbol,
                stage=data.stage.value,
                from_state=None,
                to_state=None,
                state_changed=False,
                reason="plan_not_found",
                exit_reason=None,
            )

        if plan.symbol != data.symbol:
            return FillApplyResult(
                accepted=False,
                duplicate=False,
                fill_id=data.fill_id,
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                stage=data.stage.value,
                from_state=plan.state,
                to_state=plan.state,
                state_changed=False,
                reason="symbol_mismatch",
                exit_reason=None,
            )

        try:
            from_state = PlanState(plan.state)
        except ValueError:
            from_state = PlanState.PLANNED
        to_state, changed, reason = self._next_state(from_state=from_state, stage=data.stage)
        if changed:
            plan.state = to_state.value
        previous_fills = self.fill_repo.list_for_plans(plan_ids=[plan.plan_id], symbol=plan.symbol)
        exit_event = self.exit_engine.evaluate(
            plan=plan,
            stage=data.stage,
            fill_ts=data.fill_ts,
            price=data.price,
            fee=data.fee,
            payload=data.payload,
            previous_fills=previous_fills,
        )
        payload = exit_event.metadata
        self._update_plan_validity(
            plan=plan,
            stage=data.stage,
            fill_id=data.fill_id,
            fill_ts=data.fill_ts,
            price=data.price,
            payload=payload,
        )
        self.plan_repo.db.add(plan)

        fill = ExecutionFill(
            fill_id=data.fill_id,
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            stage=data.stage.value,
            fill_ts=data.fill_ts,
            price=data.price,
            qty=data.qty,
            fee=data.fee,
            from_state=from_state.value,
            to_state=to_state.value,
            state_changed=changed,
            payload=payload,
            strategy_version=self.strategy_version,
        )
        self.fill_repo.add(fill)
        tracker = get_execution_lane_tracker()
        is_variant = bool(dict(plan.validity or {}).get("transition_edge_variant_applied"))
        if data.stage == ExecutionFillStage.ENTRY:
            tracker.record_filled(is_variant=is_variant)
        elif data.stage == ExecutionFillStage.CLOSED:
            realized_r = payload.get("realized_r")
            try:
                realized_r_value = float(realized_r) if realized_r is not None else None
            except (TypeError, ValueError):
                realized_r_value = None
            tracker.record_closed(is_variant=is_variant, realized_r=realized_r_value)

        return FillApplyResult(
            accepted=True,
            duplicate=False,
            fill_id=fill.fill_id,
            plan_id=fill.plan_id,
            symbol=fill.symbol,
            stage=fill.stage,
            from_state=fill.from_state,
            to_state=fill.to_state,
            state_changed=changed,
            reason=reason,
            exit_reason=exit_event.exit_reason,
        )

    def _next_state(self, *, from_state: PlanState, stage: ExecutionFillStage) -> tuple[PlanState, bool, str]:
        target = self._stage_to_state[stage]
        if from_state == PlanState.ARCHIVED:
            return from_state, False, "archived_plan"

        cur_rank = self._state_rank.get(from_state, 0)
        target_rank = self._state_rank.get(target, 0)
        if cur_rank >= target_rank:
            return from_state, False, "non_forward_transition"

        return target, True, "applied"

    @staticmethod
    def _update_plan_validity(
        *,
        plan,
        stage: ExecutionFillStage,
        fill_id: str,
        fill_ts: datetime,
        price: float,
        payload: dict[str, Any],
    ) -> None:
        if stage not in {ExecutionFillStage.PARTIAL_EXIT, ExecutionFillStage.CLOSED}:
            return

        validity = dict(plan.validity or {})
        exit_events = list(validity.get("exit_events") or [])
        event = {
            "fill_id": fill_id,
            "stage": stage.value,
            "exit_reason": payload.get("exit_reason"),
            "exit_ts": payload.get("exit_ts"),
            "exit_price": float(payload.get("exit_price") or price),
            "held_bars": int(payload.get("held_bars") or 0),
            "classification_before_exit": payload.get("classification_before_exit"),
            "classification_after_exit": payload.get("classification_after_exit"),
            "trigger_detail": dict(payload.get("trigger_detail") or {}),
            "realized_r": payload.get("realized_r"),
            "remaining_qty": payload.get("remaining_qty"),
        }
        exit_events.append(event)
        validity["exit_events"] = exit_events[-10:]
        validity["last_exit_event"] = dict(event)
        validity["last_exit_reason"] = payload.get("exit_reason")
        validity["last_exit_ts"] = payload.get("exit_ts") or fill_ts.isoformat()
        validity["last_exit_price"] = float(payload.get("exit_price") or price)

        if stage == ExecutionFillStage.PARTIAL_EXIT:
            validity["partial_exit_count"] = int(validity.get("partial_exit_count", 0) or 0) + 1

        if stage == ExecutionFillStage.CLOSED:
            validity["final_exit_reason"] = payload.get("exit_reason")
            validity["final_exit_ts"] = payload.get("exit_ts") or fill_ts.isoformat()
            validity["final_exit_price"] = float(payload.get("exit_price") or price)
            validity["final_exit_realized_r"] = payload.get("realized_r")
            validity["final_exit_held_bars"] = int(payload.get("held_bars") or 0)
            validity["final_exit_classification_before"] = payload.get("classification_before_exit")
            validity["final_exit_classification_after"] = payload.get("classification_after_exit")
            validity["final_exit_trigger_detail"] = dict(payload.get("trigger_detail") or {})

        plan.validity = validity
