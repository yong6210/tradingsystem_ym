"""Offline integrated v1 trial. Reviewed zone manifests and explicit limits required.

No exchange transport, automatic zone selection, or fabricated decision-close fills.
Controller/ledger are reused; all new-path sizing uses ExampleCosts and review_capacity.
"""
from copy import deepcopy
from decimal import ROUND_CEILING
import hashlib
import json
from .models import Costs, dec, positive, jsonable, require_flags
from .directional_cycling import DirectionalCycling
from .cycling_orders import CyclingOrders, CyclingOrder
from .position_alternatives import PositionExample, alternative
from .campaign_recovery_review import campaign_recovery_mark, net_if_closed
from .recovery_capacity_review import review_capacity
from .round_trip_review import round_trip


SUPPORTED_CONFIG_SHA256 = '6a097ce90b17142d661f2dcac76fdc3eb6c19fec6447affeef8ffaef6f8c2e44'


class CyclingTrialEngine:
    def __init__(self, *, config, lower, upper, execution, exits, costs, requested,
                 purpose, starting_equity, minimum_quantity, minimum_notional,
                 max_age_ms, initial_side=None, initial_time_ms=0):
        if config['version']!='cycling-decision-trial-v1' or config['live_orders'] is not False:
            raise ValueError('offline v1 configuration required')
        if hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()!=SUPPORTED_CONFIG_SHA256:
            raise ValueError('changed trial rules require a new implementation version')
        if lower.high>=upper.low:raise ValueError('distinct nonoverlapping core bands required')
        if purpose not in ('nearby_cycle','campaign_recovery'):raise ValueError('declare purpose')
        if set(execution)!={-1,1} or set(exits)!={-1,1}:raise ValueError('symmetric manifest required')
        zones=[lower,upper,*execution.values(),*exits.values()]
        for z in zones:
            if not z.valid or not z.evidence.strip() or z.available_ms>initial_time_ms:
                raise ValueError('reviewed, available manifest required')
        bykey={}
        for z in zones:
            if z.key in bykey and z!=bykey[z.key]:raise ValueError('conflicting zone manifest')
            bykey[z.key]=z
        self.config=deepcopy(config)
        self.config_sha256=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
        self.core={1:lower,-1:upper};self.boundary={1:upper,-1:lower}
        self.execution=dict(execution);self.exits=dict(exits);self.costs=costs
        self.requested=positive(requested);self.purpose=purpose;self.equity=positive(starting_equity)
        self.minimum_quantity=positive(minimum_quantity);self.minimum_notional=dec(minimum_notional)
        if type(max_age_ms) is not int or max_age_ms<0 or self.minimum_notional<0:raise ValueError('invalid limits')
        self.max_age_ms=max_age_ms
        self.model=DirectionalCycling(costs.step)
        order_costs=Costs(costs.fee,costs.slippage,costs.tick,costs.step,minimum_quantity,minimum_notional)
        self.orders=CyclingOrders(self.model,order_costs)
        self.zones=bykey;self.last=None;self.clock=initial_time_ms;self.previous={}
        self.departed={1:False,-1:False};self.crossed={1:False,-1:False}
        self.weak=False;self.local_failed=False;self.growth=0;self.reduced_growth=-1
        self.queued_half=False;self.pending_half=None;self.last_basis=None;self.grown_orders=set()
        self.submitted={};self.order_bases={};self.used=set();self.journal=[]
        if initial_side is not None:self._direction(initial_side,initial_time_ms,'explicit initial scenario hypothesis')

    def _direction(self,side,t,reason):
        kind='initial' if self.model.direction is None else 'maintain' if side==self.model.direction else 'reversal'
        assessment=dict(scope='main_trend',confirmed=True,kind=kind,
            evidence_ids=[self.core[side].key,self.boundary[side].key],
            invalidation_condition='frozen origin adverse break followed by separate failed retest')
        if kind=='reversal':assessment['prior_thesis_invalidated_by']=reason
        args=dict(timeframe='registered bands; no mandatory direction timeframe',observed_ms=t,reason=reason,assessment=assessment)
        if kind=='reversal':self.orders.request_transition(side,**args)
        else:self.orders.set_direction(side,**args)
        self.weak=False;self.local_failed=False
        self.journal.append(dict(time_ms=t,action='direction_'+kind,side=side,reason=reason))

    def _position(self):
        m=self.model
        return PositionExample(m.position_side or m.direction or 1,m.quantity,m.average,m.realized_gross,
                               m.net_costs,m.position_costs,self.equity)

    @staticmethod
    def _geometry(z,b):
        return dict(touch=b.low<=z.high and b.high>=z.low,
            whole=1 if b.low>z.high else -1 if b.high<z.low else 0,
            close=1 if b.close>z.high else -1 if b.close<z.low else 0,
            ambiguous=b.low<z.low and b.high>z.high)

    def _emit(self,t,action,**data):
        row=dict(time_ms=t,action=action,**data);self.journal.append(row);return row

    def _id(self,t,kind):return f'{kind}:{t}:{len(self.orders.orders)}'

    def _remember_order(self,order,t,basis=None):
        self.submitted[order.id]=t
        if basis:self.order_bases[order.id]=basis
        return self._emit(t,'order',order_id=order.id,kind=order.kind,quantity=str(order.quantity))

    def observe(self,bar,*,capacity=None,liquidity_qty=0,execution_ok=False,funding_known=False):
        require_flags(execution_ok,funding_known)
        if self.orders.locked or self.orders.restart_required:
            return dict(time_ms=bar.received_ms,action='reconciliation_required')
        if self.last is not None and bar==self.last:return self._emit(bar.received_ms,'duplicate_bar')
        if (self.last is not None and bar.end_ms!=self.last.end_ms+60000) or bar.received_ms<self.clock:
            raise ValueError('repair missing/revised/out-of-order input before replay')
        self.journal.append(dict(action='observation',time_ms=bar.received_ms,bar=jsonable(bar),
            capacity=jsonable(capacity),liquidity_qty=str(liquidity_qty),
            execution_ok=execution_ok,funding_known=funding_known))
        g={k:self._geometry(z,bar) for k,z in self.zones.items()};prev=self.previous
        self.last=bar;self.clock=bar.received_ms;self.previous=g;t=bar.received_ms
        extra_retracement=self._observe_reduction_references(bar)
        if self.orders.locked or self.orders.restart_required:return self._emit(t,'reconciliation_required')
        if self.orders.transition:return self._advance_exit(t,bar.close,execution_ok and funding_known)
        origin,decision=self._direction_observation(g,prev,bar,execution_ok,funding_known)
        if decision is not None:return decision
        side=self.model.direction
        if self.last_basis and g[self.last_basis]['close']==-side:self.local_failed=True
        exit_zone=self.exits[side];out=g[exit_zone.key];prior=prev.get(exit_zone.key,{})
        retracement=(self.model.quantity and self.growth!=self.reduced_growth and
            ((prior.get('close')==-side and out['touch'] and out['close']==-side and not out['ambiguous']) or extra_retracement))
        coordinated=self._coordinate_pending_orders(bar,g,prev,capacity,execution_ok,funding_known)
        if coordinated is not None:return coordinated
        active=self.orders.active
        if active:
            if active.kind=='increase':
                if retracement:self.queued_half=True
                if self.weak or self.local_failed or self.queued_half:self.orders.request_cancel(active.id)
            return self._emit(t,'await_order_reconciliation',order_id=active.id)
        if self.pending_half and self.model.reduction and self.model.reduction.remaining:
            blocked=self._pending_reduction_block_reason()
            if blocked:return self._emit(t,blocked)
            if not execution_ok or not funding_known:return self._emit(t,'execution_unknown')
            if not self.orders.costs.executable(self.model.reduction.remaining,bar.close):
                return self._emit(t,'minimum_reduction_unresolved')
            order=self._resume_reduction(t,bar.close)
            return self._remember_order(order,t)
        fresh=capacity is not None and 0<=t-capacity.observed_ms<=self.max_age_ms
        if self.model.quantity and fresh:
            p=self._position()
            violated=self._violated(p,capacity,bar.close)
            if violated:
                if self.local_failed and execution_ok and funding_known:
                    return self._trim(t,bar.close,capacity)
                return self._emit(t,'exposure_review_no_increase')
        if retracement or (self.queued_half and self.model.quantity):
            if not execution_ok or not funding_known:return self._emit(t,'execution_unknown')
            event=self._reduction_event_id()
            quantity=(self.model.quantity/2/self.costs.step).to_integral_value(rounding=ROUND_CEILING)*self.costs.step
            if not self.orders.costs.executable(quantity,bar.close):return self._emit(t,'minimum_reduction_unresolved')
            order=self.orders.retracement(self._id(t,'reduce'),event,reference_price=bar.close)
            self.pending_half=event;self.reduced_growth=self.growth;self.queued_half=False
            return self._remember_order(order,t)
        if origin['ambiguous']:return self._emit(t,'ambiguous_origin_no_increase')
        if self.weak:return self._emit(t,'direction_weakened_no_increase')
        blocked=self._increase_permission()
        if blocked:return self._emit(t,blocked)
        z=self.execution[side];here=g[z.key];before=prev.get(z.key,{})
        if not (before.get('whole')==side and here['touch'] and here['close']==side and not here['ambiguous']):
            return self._emit(t,'wait')
        if not execution_ok or not funding_known:return self._emit(t,'execution_unknown')
        reaction=(z.key,bar.end_ms)
        if reaction in self.used:return self._emit(t,'reaction_already_used')
        p=self._position()
        result=review_capacity(p,self.costs,mark=bar.close,quote_ms=t,capacity=capacity,requested=self.requested,
            liquidity_qty=liquidity_qty,minimum_quantity=self.minimum_quantity,minimum_notional=self.minimum_notional,
            now_ms=t,max_age_ms=self.max_age_ms)
        if result['status']!='capacity_calculated':return self._emit(t,result['status'])
        target=self._increase_target(side,bar.close,exit_zone)
        if side*(target-bar.close)<=0:return self._emit(t,'target_not_favorable')
        if self.purpose=='nearby_cycle' or not p.quantity:
            if round_trip(self.costs,side=side,quantity=result['capacity_quantity'],entry_mark=bar.close,exit_mark=target)['net']<=0:
                return self._emit(t,'target_fails_cost_gate')
        else:
            old=campaign_recovery_mark(p,self.costs);new=result['campaign_recovery_mark']
            if old is None or new is None or side*(old-new)<=0:return self._emit(t,'recovery_not_improved')
        order=CyclingOrder(self._id(t,'increase'),'increase',result['capacity_quantity'],side,
                           result['review']['execution_price'],None)
        self.orders._new(order.id);self.orders.orders[order.id]=order;self.used.add(reaction)
        self.local_failed=False
        return self._remember_order(order,t,z.key)

    def _direction_observation(self,g,prev,bar,execution_ok,funding_known):
        t=bar.received_ms
        side=self.model.direction
        if side is None:
            confirmed=[]
            for candidate in (1,-1):
                a=g[self.core[candidate].key];b=g[self.boundary[candidate].key]
                pa=prev.get(self.core[candidate].key,{});pb=prev.get(self.boundary[candidate].key,{})
                if pa.get('touch') and a['whole']==candidate:self.departed[candidate]=True
                was_crossed=self.crossed[candidate]
                if self.departed[candidate] and b['close']==candidate and not b['ambiguous']:self.crossed[candidate]=True
                if was_crossed and pb.get('whole')==candidate and b['touch'] and b['close']==candidate and not b['ambiguous']:
                    confirmed.append(candidate)
            if len(confirmed)==1:
                self._direction(confirmed[0],t,'origin departure, distinct boundary crossing and later favorable retest')
                return None,self._emit(t,'direction_confirmed_wait_new_reaction')
            return None,self._emit(t,'direction_unassessed')
        origin=g[self.core[side].key];po=prev.get(self.core[side].key,{})
        was_weak=self.weak
        if origin['close']==-side:self.weak=True
        elif origin['close']==side:self.weak=False
        if was_weak and po.get('whole')==-side and origin['touch'] and origin['close']==-side and not origin['ambiguous']:
            self._direction(-side,t,'frozen origin broken and separately retested on opposite side')
            self.pending_half=None;self.queued_half=False
            return None,self._advance_exit(t,bar.close,execution_ok and funding_known)
        return origin,None

    def _coordinate_pending_orders(self,bar,g,prev,capacity,execution_ok,funding_known):
        return None

    def _reduction_event_id(self):
        return f'half:growth:{self.growth}'

    def _pending_reduction_block_reason(self):
        return None

    def _resume_reduction(self,t,mark):
        return self.orders.retracement(self._id(t,'reduce'),self.pending_half,reference_price=mark)

    def _increase_target(self,side,mark,exit_zone):
        return exit_zone.low if side==1 else exit_zone.high

    def _observe_reduction_references(self,bar):
        return False

    def _increase_permission(self):
        return None

    def _advance_exit(self,t,mark,execution_ready):
        if self.orders.active:return self._emit(t,'await_transition_reconciliation')
        if not self.orders.transition:return self._emit(t,'new_direction_wait_reaction')
        if not execution_ready:return self._emit(t,'execution_unknown')
        if self.model.quantity and not self.orders.costs.executable(self.model.quantity,mark):
            return self._emit(t,'minimum_exit_unresolved')
        order=self.orders.continue_transition(self._id(t,'exit'),reference_price=mark)
        return self._remember_order(order,t) if order else self._emit(t,'flat_wait_new_reaction')

    def _violated(self,p,cap,mark,free=None):
        if free is None:free=cap.free_margin
        return (p.quantity>cap.maximum_total or free<cap.reserve_margin or
            any(net_if_closed(p,self.costs,mark-p.side*move)<-cap.stress_loss_budget for move in cap.stress_moves))

    def _trim(self,t,mark,cap):
        p=self._position();step=self.costs.step;n=int(p.quantity/step)
        minimum=max(self.minimum_quantity,self.minimum_notional/mark)
        low=max(1,int((minimum/step).to_integral_value(rounding=ROUND_CEILING)))
        # v1 weak trim must remain partial; do not silently turn it into full exit.
        high=n-1
        def estimate(k):
            q=k*step
            r=alternative(p,self.costs,mark=mark,action='partial_loss_example',quantity=q,stress_moves=cap.stress_moves)
            free=cap.free_margin+q*cap.margin_per_unit+r['change_at_same_mark']
            return r,free
        if low>high:return self._emit(t,'partial_trim_unresolved')
        r,free=estimate(high)
        if self._violated(r['after'],cap,mark,free):return self._emit(t,'partial_trim_unresolved')
        while low<high:
            mid=(low+high)//2;r,free=estimate(mid)
            if self._violated(r['after'],cap,mark,free):low=mid+1
            else:high=mid
        qty=low*step
        if not self.orders.costs.executable(qty,mark):return self._emit(t,'partial_trim_minimum_unresolved')
        order=CyclingOrder(self._id(t,'trim'),'trim',qty,self.model.position_side,None,None)
        self.orders._new(order.id);self.orders.orders[order.id]=order
        return self._remember_order(order,t)

    def fill(self,fill_id,order_id,quantity,price,*,received_ms,fee=0):
        if received_ms<=self.submitted[order_id] or received_ms<self.clock:
            raise ValueError('fills must follow the decision and current event clock')
        order=self.orders.orders[order_id]
        changed=self.orders.fill(fill_id,order_id,quantity,price,fee)
        self.clock=received_ms
        if changed and order.kind=='increase':
            if order_id not in self.grown_orders:
                self.growth+=1;self.grown_orders.add(order_id)
            self.last_basis=self.order_bases[order_id]
        self.journal.append(dict(time_ms=received_ms,action='fill',fill_id=fill_id,order_id=order_id,quantity=str(quantity),price=str(price),fee=str(fee),applied=changed))
        return changed
