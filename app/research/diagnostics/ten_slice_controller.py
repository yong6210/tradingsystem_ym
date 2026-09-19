"""E054 budget controller. Research assumptions, not discretionary trade replication.

Budget units represent allocated entry margin including lot-rounding residue,
not mark-to-market exchange margin. Actual filled entry margin can be smaller.
The account engine keeps average-cost PnL regardless of the budget-lot selection.
"""
from dataclasses import dataclass
import math


@dataclass
class Slice:
    qty: float
    margin: float


class TenSliceController:
    def __init__(self, equity, leverage, step=.001):
        if equity <= 0 or leverage <= 0 or step <= 0:
            raise ValueError('positive equity, leverage and step required')
        self.unit_margin = equity / 10
        self.leverage = leverage
        self.step = step
        self.lots = []
        self.defensive = False
        self.last_add = None

    @property
    def qty(self):
        return sum(x.qty for x in self.lots)

    @property
    def units(self):
        return sum(x.margin for x in self.lots) / self.unit_margin

    def floor(self, qty):
        return math.floor((qty + 1e-12) / self.step) * self.step

    def proposed_add(self, price):
        # The first study reserves remaining five units until a reduction resets state.
        if self.defensive or self.units + 1 > 5 + 1e-8:
            return 0.
        return self.floor(self.unit_margin * self.leverage / price)

    def record_add(self, qty, fill_price):
        margin = qty * fill_price / self.leverage
        if qty <= 0 or margin > self.unit_margin + 1e-8 or self.defensive:
            raise ValueError('invalid one-tenth addition')
        self.lots.append(Slice(qty, self.unit_margin))
        self.last_add = fill_price
        if self.units > 4 + 1e-8:
            self.defensive = True

    def reduction(self, target_units, mode):
        if mode not in ('proportional', 'newest'):
            raise ValueError(mode)
        if not 0 <= target_units < self.units:
            return self.qty
        budget_to_remove = (self.units - target_units) * self.unit_margin
        if mode == 'proportional':
            wanted = self.qty * target_units / self.units
        else:
            removed_qty = 0.
            for lot in reversed(self.lots):
                take = min(budget_to_remove, lot.margin)
                removed_qty += lot.qty * take / lot.margin
                budget_to_remove -= take
                if budget_to_remove <= 1e-9:
                    break
            wanted = self.qty - removed_qty
        return self.floor(max(0., wanted))

    def record_reduction(self, new_qty, mode):
        old_qty = self.qty
        if new_qty < 0 or new_qty > old_qty + 1e-9:
            raise ValueError('invalid reduction')
        if mode == 'proportional':
            factor = new_qty / old_qty if old_qty else 0.
            self.lots = [Slice(x.qty * factor, x.margin * factor) for x in self.lots if factor]
        elif mode == 'newest':
            remaining = old_qty - new_qty
            for lot in reversed(self.lots):
                take = min(remaining, lot.qty)
                lot.margin *= (lot.qty - take) / lot.qty
                lot.qty -= take
                remaining -= take
            self.lots = [x for x in self.lots if x.qty > 1e-10]
        else:
            raise ValueError(mode)
        # Collapse proportional remnants so old lot count cannot lock future cycles.
        if self.units <= 3 + 1e-8:
            self.lots = [Slice(self.qty, self.units * self.unit_margin)] if self.qty else []
            self.defensive = False


def action(controller, side, price, atr, favorable_reversal, adverse_reversal,
           near_support, near_resistance, average, fee_slip):
    """Fixed first-study rules; inputs must be known before the execution open."""
    if controller.defensive:
        if side * (price - controller.last_add) <= -2 * atr:
            return 'cut', 2., 'proportional'
        if favorable_reversal and side * (price - controller.last_add) >= atr:
            return 'rebound_trim', 3., 'newest'
        return 'wait', None, None
    take_zone = near_resistance if side > 0 else near_support
    if controller.units > 1.1 and take_zone and adverse_reversal and side * (price - average) > 2 * fee_slip * price:
        return 'profit_trim', max(1., controller.units - 1.), 'proportional'
    add_zone = near_support if side > 0 else near_resistance
    if add_zone and favorable_reversal and side * (price - controller.last_add) <= -atr:
        return 'add', None, None
    return 'wait', None, None
