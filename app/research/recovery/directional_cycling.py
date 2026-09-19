"""Isolated, fill-driven linear-contract cycling model; no live order routing.

Direction and retracement decisions are explicit external inputs. This module
does not invent a four-hour trend detector or entry sizing policy.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

from .models import dec, positive


@dataclass
class Reduction:
    event_id: str
    basis: Decimal
    target: Decimal
    filled: Decimal = Decimal(0)

    @property
    def remaining(self):
        return self.target - self.filled


class DirectionalCycling:
    def __init__(self, step):
        self.step = positive(step)
        self.direction = None
        self.position_side = None
        self.quantity = dec(0)
        self.average = None
        self.realized_gross = dec(0)
        self.net_costs = dec(0)
        self.position_costs = dec(0)
        self.reduction = None
        self._reductions = {}
        self._fills = {}
        self._funding = {}
        self._direction_time = -1
        self._direction_signature = None
        self.events = []

    def set_direction(self, side, *, timeframe, observed_ms, reason):
        """Record an externally assessed 4h direction, not a raw candle vote."""
        if type(side) is not int or side not in (-1, 1):
            raise ValueError('invalid direction')
        if timeframe != '4h' or not reason.strip():
            raise ValueError('four-hour assessment and reason required')
        if type(observed_ms) is not int or observed_ms < 0:
            raise ValueError('invalid assessment time')
        signature = (side, reason)
        if observed_ms < self._direction_time:
            raise ValueError('stale assessment')
        if observed_ms == self._direction_time:
            if signature != self._direction_signature:
                raise ValueError('conflicting assessment')
            return
        self.direction = side
        self._direction_time = observed_ms
        self._direction_signature = signature
        self.events.append(dict(action='set_direction', args=dict(side=side, timeframe=timeframe,
                           observed_ms=observed_ms, reason=reason)))

    def _quantity(self, value):
        qty = positive(value)
        if qty % self.step:
            raise ValueError('quantity is not step aligned')
        return qty

    def increase(self, fill_id, side, quantity, price, fee=0):
        """Replay an admitted same-direction fill; not an exchange reconciler."""
        return self._fill(fill_id, 'increase', side, quantity, price, fee, None)

    def reduce(self, fill_id, quantity, price, fee=0, *, event_id=None):
        return self._fill(fill_id, 'reduce', None, quantity, price, fee, event_id)

    def _fill(self, fill_id, kind, side, quantity, price, fee, event_id):
        qty, px, cost = self._quantity(quantity), positive(price), dec(fee)
        signature = (kind, side, qty, px, cost, event_id)
        if not fill_id or cost < 0:
            raise ValueError('invalid fill')
        if fill_id in self._fills:
            if self._fills[fill_id] != signature:
                raise ValueError('conflicting duplicate fill')
            return False
        if kind == 'increase':
            if type(side) is not int or side not in (-1, 1) or side != self.direction:
                raise ValueError('increase must follow assessed direction')
            if self.quantity and side != self.position_side:
                raise ValueError('flatten existing position before reversing')
            if self.reduction and self.reduction.remaining:
                raise ValueError('finish reduction before increasing')
            self.average = ((self.average or dec(0)) * self.quantity + qty * px) / (self.quantity + qty)
            self.quantity += qty
            self.position_side = side
            self.position_costs += cost
        else:
            if qty > self.quantity:
                raise ValueError('reduction exceeds position')
            pending = self.reduction and self.reduction.remaining > 0
            if event_id is not None:
                if not pending or self.reduction.event_id != event_id:
                    raise ValueError('no matching active reduction')
                if qty > self.reduction.remaining:
                    raise ValueError('fill exceeds reduction target')
            elif pending:
                raise ValueError('active reduction requires event attribution')
            self.realized_gross += self.position_side * qty * (px - self.average)
            self.position_costs *= (self.quantity - qty) / self.quantity
            self.quantity -= qty
            if event_id is not None:
                self.reduction.filled += qty
            if not self.quantity:
                self.average = None
                self.position_side = None
            # A reduction never changes the remaining pooled average or bias.
        self.net_costs += cost
        self._fills[fill_id] = signature
        args = dict(fill_id=fill_id, quantity=qty, price=px, fee=cost)
        args.update(dict(side=side) if kind == 'increase' else dict(event_id=event_id))
        self.events.append(dict(action=kind, args=args))
        return True

    def begin_retracement(self, event_id, fraction='0.5'):
        """Freeze total-position basis once; retries never halve it again."""
        fraction = dec(fraction)
        if not event_id or not dec('0.5') <= fraction <= 1:
            raise ValueError('reduce at least half of total position')
        if event_id in self._reductions:
            old_fraction, reduction = self._reductions[event_id]
            if old_fraction != fraction:
                raise ValueError('conflicting reduction event')
            return reduction
        if not self.quantity or (self.reduction and self.reduction.remaining):
            raise ValueError('position required and previous reduction must finish')
        target = (self.quantity * fraction / self.step).to_integral_value(rounding=ROUND_CEILING) * self.step
        self.reduction = Reduction(event_id, self.quantity, target)
        self._reductions[event_id] = (fraction, self.reduction)
        self.events.append(dict(action='begin_retracement', args=dict(event_id=event_id, fraction=fraction)))
        return self.reduction

    def supersede_reduction(self, reason):
        """Retain old accounting while replacing the intent with a full exit."""
        if not reason.strip():
            raise ValueError('supersession reason required')
        if self.reduction is not None:
            self.reduction = None
            self.events.append(dict(action='supersede_reduction', args=dict(reason=reason)))

    def funding(self, event_id, signed_cost):
        """Positive means paid; negative means received. Apply once per event."""
        cost = dec(signed_cost)
        if not event_id:
            raise ValueError('funding event required')
        if event_id in self._funding:
            if self._funding[event_id] != cost:
                raise ValueError('conflicting funding event')
            return False
        self.net_costs += cost
        if self.quantity:
            self.position_costs += cost
        self._funding[event_id] = cost
        self.events.append(dict(action='funding', args=dict(event_id=event_id, signed_cost=cost)))
        return True

    def total_pnl(self, mark):
        mark = positive(mark)
        unrealized = self.position_side * self.quantity * (mark - self.average) if self.quantity else dec(0)
        return self.realized_gross - self.net_costs + unrealized

    def break_evens(self, exit_fee_rate=0):
        """Exit fill prices, including supplied proportional exit fee estimate."""
        rate = dec(exit_fee_rate)
        if not 0 <= rate < 1:
            raise ValueError('invalid exit fee')
        if not self.quantity:
            return dict(position=None, campaign=None)
        denominator = self.quantity * (self.position_side - rate)
        base = self.position_side * self.quantity * self.average
        position = (base + self.position_costs) / denominator
        campaign = (base - self.realized_gross + self.net_costs) / denominator
        return dict(position=position if position > 0 else None,
                    campaign=campaign if campaign > 0 else None)
