"""Capacity-only review using explicit limits, never market/entry approval."""
from .models import dec, positive, floor_step
from .position_alternatives import alternative
from .campaign_recovery_review import net_if_closed, campaign_recovery_mark


def review_capacity(position,costs,*,mark,quote_ms,capacity,requested,liquidity_qty,
                    minimum_quantity,minimum_notional,now_ms,max_age_ms):
    mark=positive(mark);requested=positive(requested)
    for t in (quote_ms,now_ms,max_age_ms):
        if type(t) is not int or t<0:raise ValueError('invalid time')
    values=[dec(x) for x in (liquidity_qty,minimum_quantity,minimum_notional)]
    if any(x<0 for x in values):raise ValueError('negative execution limit')
    liquidity,min_qty,min_notional=values
    if position.quantity%costs.step:raise ValueError('position step mismatch')
    base=dict(entry_approved=False,orders_generated=0,
              interpretation='capacity ceiling only; no direction, location, open-order or funding validation')
    if capacity is None:
        return dict(**base,status='missing_capacity',capacity_quantity=None)
    stale=[label for label,t in [('quote',quote_ms),('capacity',capacity.observed_ms)] if not 0<=now_ms-t<=max_age_ms]
    if stale:return dict(**base,status='unavailable_snapshot',reasons=stale,capacity_quantity=None)
    entry=costs.execution(mark,position.side)
    limits=dict(requested=requested,liquidity=liquidity,
        exposure=max(dec(0),capacity.maximum_total-position.quantity),
        margin=max(dec(0),capacity.free_margin-capacity.reserve_margin)/(capacity.margin_per_unit+entry*costs.fee))
    before=[]
    for i,move in enumerate(capacity.stress_moves):
        future=mark-position.side*move
        if future<=0:raise ValueError('nonpositive stress mark')
        existing=net_if_closed(position,costs,future)
        exit_fill=costs.execution(future,-position.side)
        unit_loss=position.side*(entry-exit_fill)+(entry+exit_fill)*costs.fee
        if unit_loss<=0:raise ValueError('adverse scenario must increase marginal loss')
        limits[f'stress_{i}']=max(dec(0),capacity.stress_loss_budget+existing)/unit_loss
        before.append(dict(mark=future,net_if_closed=existing,adverse_move=move))
    minimum=min(limits.values());quantity=floor_step(minimum,costs.step)
    limiting=[key for key,value in limits.items() if value==minimum]
    if quantity<=0 or quantity<min_qty or quantity*entry<min_notional:
        return dict(**base,status='no_executable_capacity',capacity_quantity=dec(0),limits=limits,
                    limiting=limiting,existing_stress=before)
    result=alternative(position,costs,mark=mark,action='increase',quantity=quantity,stress_moves=capacity.stress_moves)
    after=result['after']
    stress=[dict(**s,after_net_if_closed=net_if_closed(after,costs,s['mark'])) for s in before]
    return dict(**base,status='capacity_calculated',capacity_quantity=quantity,limits=limits,limiting=limiting,
        review=result,campaign_recovery_mark=campaign_recovery_mark(after,costs),stress=stress,
        reserved_margin_remaining=capacity.free_margin-quantity*(capacity.margin_per_unit+entry*costs.fee))
