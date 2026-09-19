"""Research policy: one fresh assessment after handoff, then restore valid cover.

No timeout exit and no farther target substitution. An unsettled addition is
never considered finished; partial fills count only after order reconciliation.
"""
from .cycling_order_coordination import CyclingCoordinatedEngine


class CyclingPlanRecoveryEngine(CyclingCoordinatedEngine):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.plan_recovery=None

    def _coordinate_pending_orders(self,bar,g,prev,capacity,execution_ok,funding_known):
        snapshot=None
        if self.order_handoff and not self.orders.active:
            old=self.orders.orders[self.order_handoff['order_id']]
            if self.model.direction==self.order_handoff['side']:
                intent=next(r for r in reversed(self.journal) if r['action']=='planned_reduction_intent' and r['event_id']==old.event_id)
                snapshot=dict(event_id=old.event_id,reference_id=intent['reference_id'],side=old.side,
                    quantity=self.model.quantity,growth=self.growth,settled_ms=bar.received_ms)
        row=super()._coordinate_pending_orders(bar,g,prev,capacity,execution_ok,funding_known)
        if snapshot is not None and self.order_handoff is None:self.plan_recovery=snapshot
        return row

    def observe(self,bar,**kwargs):
        duplicate=self.last==bar
        row=super().observe(bar,**kwargs)
        if duplicate or self.plan_recovery is None:return row
        p=self.plan_recovery;t=bar.received_ms
        if self.orders.locked or self.orders.restart_required:return row
        if self.orders.transition or self.model.direction!=p['side'] or not self.model.quantity:
            self.plan_recovery=None;self.replan_required=False
            return row
        if row['action']=='handoff_wait_fresh_add_reaction':return row
        p['assessment_done']=True
        if self.orders.active or self.order_handoff:return row
        # Any separately accepted reduction intent takes ownership of coverage.
        if self.pending_half is not None:
            self.plan_recovery=None
            return row
        unchanged=self.model.quantity==p['quantity'] and self.growth==p['growth']
        if unchanged and not self.model._reductions[p['event_id']][1].remaining:
            self.plan_recovery=None;self.replan_required=False
            return self._emit(t,'plan_recovery_original_target_already_filled')
        cap=kwargs.get('capacity')
        if cap is None or not 0<=t-cap.observed_ms<=self.max_age_ms:
            return self._emit(t,'plan_recovery_wait_fresh_capacity')
        if self._violated(self._position(),cap,bar.close):
            return self._emit(t,'plan_recovery_wait_capacity_resolution')
        if not kwargs.get('execution_ok',False) or not kwargs.get('funding_known',False):
            return self._emit(t,'plan_recovery_wait_execution')
        ref=next(r for r in self.reduction_references if r.id==p['reference_id'])
        if ref.id in self.retired_references or ref.side*(ref.price-bar.close)<=0:
            return self._emit(t,'plan_recovery_reference_unavailable',reference_id=ref.id)
        unchanged=self.model.quantity==p['quantity'] and self.growth==p['growth']
        if unchanged:
            old=self.model._reductions[p['event_id']][1]
            if not old.remaining:
                self.plan_recovery=None;self.replan_required=False
                return self._emit(t,'plan_recovery_original_target_already_filled')
            if not self.orders.costs.executable(old.remaining,ref.price):
                return self._emit(t,'plan_recovery_minimum_unresolved')
            try:
                self.model.resume_reduction(p['event_id'],'addition not filled; restore original outstanding target')
            except ValueError:
                return self._emit(t,'plan_recovery_prior_target_not_resumable')
            self.pending_half=p['event_id'];self.reduced_growth=self.growth
            order=self._resume_reduction(t,bar.close)
            self._emit(t,'plan_recovered_original_remaining',event_id=p['event_id'],quantity=str(old.remaining))
            row=self._remember_order(order,t)
        else:
            # plan_reduction uses the reconciled total, rounded up; keep the same
            # reference and do not infer availability from average-price improvement.
            self.reduced_growth=-1
            quantity=(self.model.quantity/2/self.costs.step).to_integral_value(rounding='ROUND_CEILING')*self.costs.step
            if not self.orders.costs.executable(quantity,ref.price):
                return self._emit(t,'plan_recovery_minimum_unresolved')
            row=self.plan_reduction(ref.id,observed_ms=t,mark=bar.close,execution_ok=True,funding_known=True)
            self._emit(t,'plan_recovered_new_total',total_quantity=str(self.model.quantity),quantity=str(quantity))
        self.plan_recovery=None
        return row

    def _increase_permission(self):
        if self.plan_recovery is not None and self.plan_recovery.get('assessment_done'):
            return 'plan_recovery_pending_no_further_increase'
        return super()._increase_permission()

    def _remember_order(self,order,t,basis=None):
        row=super()._remember_order(order,t,basis)
        if order.kind in ('reduce','limit_reduce'):
            self.plan_recovery=None
        return row
