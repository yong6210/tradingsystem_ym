"""Explicit hypothetical position alternatives, with no signal or order routing.

Free-margin output is only equity minus notional/leverage, not exchange margin
or liquidation capacity. Break-even outputs are exit fill prices, not quotes.
"""
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from .models import dec, positive


@dataclass(frozen=True)
class PositionExample:
    side: int
    quantity: Decimal
    average: Decimal | None
    realized_gross: Decimal
    paid_costs: Decimal  # Net paid fees/funding; a receipt may make this negative.
    remaining_costs: Decimal  # Costs attributed to the remaining position only.
    starting_equity: Decimal

    def __post_init__(self):
        if type(self.side) is not int or self.side not in (-1,1):
            raise ValueError('explicit hypothetical direction required')
        for name in ('quantity','realized_gross','paid_costs','remaining_costs'):
            object.__setattr__(self,name,dec(getattr(self,name)))
        object.__setattr__(self,'starting_equity',positive(self.starting_equity))
        if self.quantity<0 or (self.quantity==0)!=(self.average is None):
            raise ValueError('quantity/average mismatch')
        if self.average is not None:
            object.__setattr__(self,'average',positive(self.average))

    def pnl(self, mark):
        mark=positive(mark)
        return self.realized_gross-self.paid_costs+(self.side*self.quantity*(mark-self.average) if self.quantity else 0)


@dataclass(frozen=True)
class ExampleCosts:
    fee: Decimal
    half_spread: Decimal
    slippage: Decimal
    tick: Decimal
    step: Decimal
    leverage: Decimal

    def __post_init__(self):
        for name in ('fee','half_spread','slippage'):
            value=dec(getattr(self,name))
            if not 0<=value<1:raise ValueError('invalid friction')
            object.__setattr__(self,name,value)
        for name in ('tick','step','leverage'):
            object.__setattr__(self,name,positive(getattr(self,name)))

    def execution(self, mark, buy_side):
        value=positive(mark)*(1+buy_side*self.half_spread)*(1+buy_side*self.slippage)
        rounding=ROUND_CEILING if buy_side==1 else ROUND_FLOOR
        return (value/self.tick).to_integral_value(rounding=rounding)*self.tick


def alternative(position, costs, *, mark, action, quantity=0, stress_moves):
    """Evaluate an explicit action; never decide whether it should be taken."""
    mark=positive(mark); qty=dec(quantity)
    if position.quantity%costs.step or qty%costs.step:
        raise ValueError('quantity not step aligned')
    if action not in ('wait','increase','retracement_reduce','partial_loss_example'):
        raise ValueError('unknown action')
    if (action=='wait' and qty!=0) or (action!='wait' and qty<=0):
        raise ValueError('invalid action quantity')
    after=position; execution=None; fee=dec(0)
    if action=='increase':
        execution=costs.execution(mark,position.side)
        fee=qty*execution*costs.fee
        average=((position.average or dec(0))*position.quantity+qty*execution)/(position.quantity+qty)
        after=replace(position,quantity=position.quantity+qty,average=average,
                      paid_costs=position.paid_costs+fee,remaining_costs=position.remaining_costs+fee)
    elif action!='wait':
        if qty>position.quantity:raise ValueError('reduction exceeds position')
        if action=='retracement_reduce' and qty<position.quantity/2:
            raise ValueError('retracement reduction must be at least half of total')
        execution=costs.execution(mark,-position.side)
        fee=qty*execution*costs.fee
        remaining=position.quantity-qty
        after=replace(position,quantity=remaining,average=position.average if remaining else None,
                      realized_gross=position.realized_gross+position.side*qty*(execution-position.average),
                      paid_costs=position.paid_costs+fee,
                      remaining_costs=position.remaining_costs*remaining/position.quantity)
    net=after.pnl(mark); equity=after.starting_equity+net
    margin=after.quantity*mark/costs.leverage
    campaign_be=position_be=None
    if after.quantity:
        base=after.side*after.quantity*after.average
        denominator=after.quantity*(after.side-costs.fee)
        campaign_be=(base-after.realized_gross+after.paid_costs)/denominator
        position_be=(base+after.remaining_costs)/denominator
        campaign_be=campaign_be if campaign_be>0 else None
        position_be=position_be if position_be>0 else None
    scenarios=[]
    for distance in stress_moves:
        distance=positive(distance)
        future=mark-after.side*distance
        if future<=0:raise ValueError('nonpositive scenario mark')
        future_pnl=after.pnl(future)
        close_price=costs.execution(future,-after.side)
        close_net=(after.realized_gross-after.paid_costs +
                   after.side*after.quantity*(close_price-after.average) -
                   after.quantity*close_price*costs.fee) if after.quantity else future_pnl
        scenarios.append(dict(adverse_move=distance,mark=future,pnl=future_pnl,
                              pnl_if_closed_at_estimated_execution=close_net))
    result=dict(action=action,action_quantity=qty,execution_price=execution,action_fee=fee,
                after=after,unrealized=net-after.realized_gross+after.paid_costs,
                total_net=net,change_at_same_mark=net-position.pnl(mark),
                equity=equity,margin_proxy=margin,free_margin_proxy=equity-margin,
                free_margin_change=(equity-margin)-(position.starting_equity+position.pnl(mark)-position.quantity*mark/costs.leverage),
                position_break_even_fill=position_be,campaign_break_even_fill=campaign_be,
                adverse_scenarios=scenarios,orders_generated=0)
    return result
