"""Full-campaign exit arithmetic, including earlier realized losses and costs."""
from decimal import ROUND_CEILING, ROUND_FLOOR
from .models import positive


def net_if_closed(position,costs,mark):
    mark=positive(mark)
    if not position.quantity:return position.realized_gross-position.paid_costs
    fill=costs.execution(mark,-position.side)
    return (position.realized_gross-position.paid_costs+
            position.side*position.quantity*(fill-position.average)-position.quantity*fill*costs.fee)


def campaign_recovery_mark(position,costs):
    if not position.quantity:return None
    q=position.quantity;side=position.side
    required=(side*q*position.average-position.realized_gross+position.paid_costs)/(q*(side-costs.fee))
    if required<=0:return None
    factor=(1-side*costs.half_spread)*(1-side*costs.slippage)
    rounding=ROUND_CEILING if side==1 else ROUND_FLOOR
    mark=(required/factor/costs.tick).to_integral_value(rounding=rounding)*costs.tick
    if mark<=0:return None
    while net_if_closed(position,costs,mark)<0:
        mark+=side*costs.tick
        if mark<=0:return None
    # Closest profitable mark on the price grid, not an order or price forecast.
    while mark-side*costs.tick>0 and net_if_closed(position,costs,mark-side*costs.tick)>=0:
        mark-=side*costs.tick
    return mark
