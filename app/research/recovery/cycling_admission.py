"""Point-in-time sizing for the isolated cycling research path.

All limits are explicit caller inputs, not approved strategy defaults. Stress
prices measure capacity; crossing them does not place a stop or exit order.
"""
from dataclasses import dataclass
from decimal import Decimal

from .evidence import ZoneHistory, timestamp
from .models import Costs, Quote, dec, positive, floor_step
from .separated_execution import execution_quote


@dataclass(frozen=True)
class Capacity:
    observed_ms: int
    free_margin: Decimal
    reserve_margin: Decimal
    margin_per_unit: Decimal
    maximum_total: Decimal
    stress_loss_budget: Decimal
    stress_moves: tuple

    def __post_init__(self):
        timestamp(self.observed_ms)
        for name in ('free_margin', 'reserve_margin', 'maximum_total', 'stress_loss_budget'):
            value = dec(getattr(self, name))
            if value < 0:
                raise ValueError('negative capacity')
            object.__setattr__(self, name, value)
        object.__setattr__(self, 'margin_per_unit', positive(self.margin_per_unit))
        object.__setattr__(self, 'stress_moves', tuple(positive(x) for x in self.stress_moves))
        if not self.stress_moves:
            raise ValueError('explicit stress scenarios required')


@dataclass(frozen=True)
class Location:
    history: ZoneHistory
    side: int
    reaction_event_id: str
    entry_low: Decimal
    entry_high: Decimal

    def __post_init__(self):
        if type(self.side) is not int or self.side not in (-1, 1):
            raise ValueError('invalid location side')
        for name in ('entry_low', 'entry_high'):
            object.__setattr__(self, name, positive(getattr(self, name)))
        if self.entry_low > self.entry_high:
            raise ValueError('invalid executable entry range')


def assess_increase(model, location: Location, quote: Quote, costs: Costs,
                    capacity: Capacity, *, requested, now_ms, max_age_ms):
    """Size to exposure, liquidity, margin reserve and scenario loss ceilings.

Margin/free cash must come from the account snapshot; never infer them from
average-price improvement. Only one active order is allowed by the controller.
"""
    timestamp(now_ms)
    timestamp(max_age_ms)
    requested = positive(requested)
    if model.step != costs.step:
        raise ValueError('quantity step mismatch')
    reasons = []
    side = location.side
    if model.direction != side or (model.quantity and model.position_side != side):
        reasons.append('direction_mismatch')
    if model._direction_time > now_ms:
        reasons.append('future_direction_assessment')
    if model.reduction and model.reduction.remaining:
        reasons.append('reduction_incomplete')
    if not quote.execution_ok or not quote.funding_known:
        reasons.append('execution_or_funding_unknown')
    for label, observed in (('quote', quote.time_ms), ('capacity', capacity.observed_ms)):
        if not 0 <= now_ms - observed <= max_age_ms:
            reasons.append(label + '_not_current')
    state = location.history.as_of(now_ms)
    if not location.history.zone.valid or state['state'] != 'valid':
        reasons.append('zone_not_valid')
    events = [e for e in location.history.events if e.id in state['event_ids']]
    reaction = next((e for e in events if e.id == location.reaction_event_id), None)
    latest_reaction = next((e for e in reversed(events) if e.kind in ('reaction', 'validated')), None)
    if (reaction is None or reaction != latest_reaction or
            reaction.kind not in ('reaction', 'validated')):
        reasons.append('current_reaction_required')
    elif not 0 <= now_ms - reaction.evidence.observed_ms <= max_age_ms:
        reasons.append('reaction_not_current')
    price = execution_quote(quote, costs).entry(side)
    if not location.entry_low <= price <= location.entry_high:
        reasons.append('price_outside_declared_entry_range')
    if reasons:
        return dict(allowed=False, reasons=tuple(reasons), quantity=dec(0), price=price, scenarios=())

    limits = dict(requested=requested,
                  exposure=max(dec(0), min(capacity.maximum_total, quote.max_total_qty) - model.quantity),
                  margin=max(dec(0), capacity.free_margin - capacity.reserve_margin) /
                         (capacity.margin_per_unit + price * costs.fee),
                  quote_margin=quote.margin_room_qty, liquidity=quote.liquidity_qty)
    stress_prices = []
    # Raw executable quote is the common reference; slippage is paid once on entry.
    for i, move in enumerate(capacity.stress_moves):
        stress = quote.entry(side) - side * move
        if stress <= 0:
            raise ValueError('stress scenario has nonpositive price')
        stress_prices.append(stress)
        existing_pnl = model.total_pnl(stress) - model.quantity * stress * costs.fee
        unit_loss = side * (price - stress) + (price + stress) * costs.fee
        limits['stress_' + str(i)] = max(dec(0), capacity.stress_loss_budget + existing_pnl) / unit_loss
    quantity = floor_step(min(limits.values()), costs.step)
    if not costs.executable(quantity, price):
        return dict(allowed=False, reasons=('insufficient_capacity_or_minimum_order',),
                    quantity=dec(0), price=price, limits=limits, scenarios=())
    total = model.quantity + quantity
    average = ((model.average or dec(0)) * model.quantity + quantity * price) / total
    scenarios = tuple(dict(price=stress,
                           total_pnl=model.total_pnl(stress) + side * quantity * (stress - price)
                           - quantity * price * costs.fee - total * stress * costs.fee)
                      for stress in stress_prices)
    return dict(allowed=True, reasons=(), quantity=quantity, price=price,
                limits=limits, scenarios=scenarios, total_quantity=total, average=average,
                margin_remaining=capacity.free_margin - quantity * (capacity.margin_per_unit + price * costs.fee))
