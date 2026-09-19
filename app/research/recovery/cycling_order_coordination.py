"""Research serial handoff: cancel/reconcile before replacing a resting half plan.

A new-add candidate triggers cancellation, never reserves an addition. After
settlement a fresh reaction and ordinary admission are still required. The old
plan is explicitly superseded, not marked filled; a new plan uses actual totals.
"""
from .cycling_planned_reduction import CyclingPlannedReductionEngine


class CyclingCoordinatedEngine(CyclingPlannedReductionEngine):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.order_handoff=None;self.plan_revision=0;self.replan_required=False

    def _reduction_event_id(self):
        return super()._reduction_event_id()+f':revision:{self.plan_revision}'

    def _coordinate_pending_orders(self,bar,g,prev,capacity,execution_ok,funding_known):
        t=bar.received_ms
        if self.order_handoff:
            h=self.order_handoff
            if self.orders.active:
                return self._emit(t,'handoff_await_cancel_reconciliation',order_id=h['order_id'])
            old=self.orders.orders[h['order_id']]
            if self.model.direction!=h['side']:
                self.order_handoff=None
                return self._emit(t,'handoff_superseded_by_main_transition')
            # Terminal order is required; confirm_cancel already requires all fills.
            if old.status not in ('cancelled','filled'):
                raise ValueError('settled terminal order required')
            self.model.supersede_reduction('resting plan replaced after cancel reconciliation: '+h['purpose'])
            self.pending_half=None;self.queued_half=False
            self.plan_revision+=1
            # A fully filled original half remains completed until inventory grows.
            if old.filled<old.quantity:
                self.reduced_growth=-1;self.replan_required=True
            self.order_handoff=None
            self._emit(t,'handoff_settled',purpose=h['purpose'],old_order_id=old.id,
                old_order_filled=str(old.filled),old_order_unfilled=str(old.remaining),
                actual_quantity=str(self.model.quantity),plan_status='superseded_not_assumed_filled',replan_required=self.replan_required)
            if h['purpose']=='new_add':
                return self._emit(t,'handoff_wait_fresh_add_reaction')
            # Current bar's capacity and minimum partial trim are recomputed below.
            return None
        active=self.orders.active
        if not active or active.kind!='limit_reduce' or active.status!='open':return None
        if active.event_id in self.paused_plans:return None
        fresh=capacity is not None and 0<=t-capacity.observed_ms<=self.max_age_ms
        if not fresh:return None
        risk=self.model.quantity and self.local_failed and self._violated(self._position(),capacity,bar.close)
        side=self.model.direction;z=self.execution[side]
        here=g[z.key];before=prev.get(z.key,{})
        add=(not risk and self._increase_permission() is None and not self.weak and execution_ok and funding_known and
             before.get('whole')==side and here['touch'] and here['close']==side and not here['ambiguous'])
        if not risk and not add:return None
        purpose='capacity_reduction' if risk else 'new_add'
        self.order_handoff=dict(order_id=active.id,purpose=purpose,side=side)
        self.orders.request_cancel(active.id)
        return self._emit(t,'handoff_cancel_requested',order_id=active.id,purpose=purpose,
                          next_order_quantity=None)

    def _remember_order(self,order,t,basis=None):
        row=super()._remember_order(order,t,basis)
        if order.kind in ('reduce','limit_reduce'):self.replan_required=False
        return row

    def set_plan_paused(self, paused, **kwargs):
        row=super().set_plan_paused(paused,**kwargs)
        if paused:self.order_handoff=None
        return row
