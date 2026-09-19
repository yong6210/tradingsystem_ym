"""Explicit preplaced half-reduction intents; no automatic historical fills."""
from .cycling_reduction_engine import CyclingReductionEngine
from .models import positive,require_flags


class CyclingPlannedReductionEngine(CyclingReductionEngine):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.planned_limits={};self.paused_plans=set()

    def plan_reduction(self, reference_id, *, observed_ms, mark, execution_ok, funding_known):
        require_flags(execution_ok,funding_known)
        if type(observed_ms) is not int or observed_ms<self.clock:
            raise ValueError('ordered planning time required')
        if not execution_ok or not funding_known:raise ValueError('execution inputs required')
        mark=positive(mark)
        ref=next((r for r in self.reduction_references if r.id==reference_id),None)
        if ref is None or ref.available_ms>observed_ms or ref.id in self.retired_references:
            raise ValueError('available active reduction reference required')
        if ref.side!=self.model.position_side or ref.side!=self.model.direction:
            raise ValueError('reference must match actual inventory and direction')
        if ref.side*(ref.price-mark)<=0:raise ValueError('preplace only before target arrival')
        if self.growth==self.reduced_growth:raise ValueError('growth cycle already reduced or reserved')
        event=self._reduction_event_id()
        order=self.orders.limit_retracement(self._id(observed_ms,'limit-reduce'),event,limit_price=ref.price)
        self.planned_limits[event]=ref.price
        self.pending_half=event;self.reduced_growth=self.growth;self.clock=observed_ms
        self._emit(observed_ms,'planned_reduction_intent',reference_id=ref.id,limit_price=str(ref.price),
                   total_basis=str(self.model.reduction.basis),event_id=event)
        return self._remember_order(order,observed_ms)

    def _resume_reduction(self,t,mark):
        if self.pending_half in self.planned_limits:
            return self.orders.limit_retracement(self._id(t,'limit-reduce'),self.pending_half,
                limit_price=self.planned_limits[self.pending_half])
        return super()._resume_reduction(t,mark)

    def set_plan_paused(self, paused, *, observed_ms, reason):
        require_flags(paused)
        if type(observed_ms) is not int or observed_ms<self.clock or not isinstance(reason,str) or not reason.strip():
            raise ValueError('ordered explicit pause/resume reason required')
        if self.pending_half not in self.planned_limits or not self.model.reduction or not self.model.reduction.remaining:
            raise ValueError('unfinished planned reduction required')
        if paused:
            self.paused_plans.add(self.pending_half)
            if self.orders.active:self.orders.request_cancel(self.orders.active.id)
        else:self.paused_plans.discard(self.pending_half)
        self.clock=observed_ms
        return self._emit(observed_ms,'planned_reduction_paused' if paused else 'planned_reduction_resumed',
                          event_id=self.pending_half,reason=reason)

    def _pending_reduction_block_reason(self):
        if self.pending_half in self.paused_plans:return 'planned_reduction_paused_await_explicit_resume'
        return super()._pending_reduction_block_reason()
