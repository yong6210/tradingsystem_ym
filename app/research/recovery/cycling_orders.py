"""Serial offline orders around cycling admission and actual partial fills.

No exchange transport, automatic market signals or liquidation model. A cancel
ack must include the reconciled cumulative quantity before releasing capacity.
"""
from dataclasses import dataclass
from decimal import Decimal

from .cycling_admission import assess_increase
from .models import dec, positive


@dataclass
class CyclingOrder:
    id: str
    kind: str
    quantity: Decimal
    side: int
    price_cap: Decimal | None
    event_id: str | None
    filled: Decimal = Decimal(0)
    status: str = 'open'

    @property
    def remaining(self):
        return self.quantity - self.filled


class CyclingOrders:
    def __init__(self, model, costs):
        if model.step != costs.step:
            raise ValueError('quantity step mismatch')
        self.model, self.costs = model, costs
        self.orders = {}
        self.fills = {}
        self.used_reactions = set()
        self.locked = False
        self.restart_required = False
        self.transition = None

    @property
    def active(self):
        return next((o for o in self.orders.values() if o.status in ('open', 'cancel_pending')), None)

    def _new(self, order_id):
        if not order_id or order_id in self.orders or self.active or self.locked or self.restart_required:
            raise ValueError('unique order and settled unlocked state required')

    def increase(self, order_id, location, quote, capacity, **inputs):
        self._new(order_id)
        if self.transition:
            raise ValueError('finish trend-transition exit before increasing')
        key = (location.history.zone.key, location.reaction_event_id)
        if key in self.used_reactions:
            raise ValueError('fresh location reaction required')
        assessment = assess_increase(self.model, location, quote, self.costs, capacity, **inputs)
        if not assessment['allowed']:
            return assessment
        self.orders[order_id] = CyclingOrder(order_id, 'increase', assessment['quantity'],
                                            location.side, assessment['price'], None)
        # Reserve evidence on submission, even if subsequently cancelled unfilled.
        self.used_reactions.add(key)
        return assessment

    def retracement(self, order_id, event_id, *, reference_price, fraction='0.5'):
        self._new(order_id)
        if self.transition:
            raise ValueError('trend-transition exit takes priority')
        price = positive(reference_price)
        # Validate without changing the reduction event on minimum-order failure.
        from decimal import ROUND_CEILING
        fraction = dec(fraction)
        if not dec('.5') <= fraction <= 1:
            raise ValueError('reduce at least half')
        prior = self.model._reductions.get(event_id)
        if prior is not None:
            if prior[1] is not self.model.reduction:
                raise ValueError('reduction event was superseded')
            if prior[0] != fraction:
                raise ValueError('conflicting reduction event')
            quantity = prior[1].remaining
        else:
            quantity = (self.model.quantity * fraction / self.costs.step).to_integral_value(rounding=ROUND_CEILING) * self.costs.step
        if not self.costs.executable(quantity, price):
            raise ValueError('reduction below minimum order; explicit resolution required')
        reduction = self.model.begin_retracement(event_id, fraction)
        self.orders[order_id] = CyclingOrder(order_id, 'reduce', reduction.remaining,
                                            self.model.position_side, None, event_id)
        return self.orders[order_id]

    def request_cancel(self, order_id):
        order = self.orders[order_id]
        if order.status == 'open':
            order.status = 'cancel_pending'

    def confirm_cancel(self, order_id, cumulative_filled):
        order = self.orders[order_id]
        cumulative = dec(cumulative_filled)
        if cumulative != order.filled:
            raise ValueError('reconcile missing fills before acknowledging cancellation')
        if order.status in ('filled', 'cancelled'):
            return
        if order.status != 'cancel_pending':
            raise ValueError('cancellation was not requested')
        order.status = 'cancelled'

    def fill(self, fill_id, order_id, quantity, price, fee=0):
        order = self.orders[order_id]
        qty, price, fee = self.model._quantity(quantity), positive(price), dec(fee)
        signature = (order_id, qty, price, fee)
        if fill_id in self.fills:
            if self.fills[fill_id] != signature:
                raise ValueError('conflicting duplicate fill')
            return False
        if fill_id in self.model._fills:
            self.locked = True
            raise ValueError('fill already exists outside controller; reconciliation required')
        if order.status not in ('open', 'cancel_pending'):
            self.locked = True
            raise ValueError('unexpected terminal-order fill; external reconciliation required')
        if qty > order.remaining or fee < 0:
            raise ValueError('invalid fill quantity or fee')
        if order.kind == 'increase':
            if order.side * (price - order.price_cap) > 0:
                raise ValueError('fill exceeds entry limit')
            self.model.increase(fill_id, order.side, qty, price, fee)
        else:
            self.model.reduce(fill_id, qty, price, fee, event_id=order.event_id)
        order.filled += qty
        if not order.remaining:
            order.status = 'filled'
        self.fills[fill_id] = signature
        if self.transition and not self.model.quantity and not self.active:
            self.model.set_direction(**self.transition)
            self.model.supersede_reduction('trend transition completed flat')
            self.transition = None
        return True

    def set_direction(self, side, **assessment):
        if self.active:
            raise ValueError('cancel and reconcile active order before direction change')
        if self.locked or self.restart_required or self.transition:
            raise ValueError('reconciliation required')
        if self.model.quantity and self.model.position_side != side:
            self.request_transition(side, **assessment)
        else:
            self.model.set_direction(side, **assessment)

    def request_transition(self, side, **assessment):
        """Explicit 4h assessment; cancellation first, no reversal fill yet."""
        from copy import deepcopy
        if self.locked or self.restart_required:
            raise ValueError('reconciliation required')
        candidate = dict(side=side, **assessment)
        if self.transition:
            if self.transition != candidate:
                raise ValueError('finish pending transition before another assessment')
            return
        probe = deepcopy(self.model)
        probe.set_direction(**candidate)  # Validate before mutating/cancelling.
        if side == self.model.direction:
            raise ValueError('transition requires a changed four-hour direction')
        self.transition = candidate
        if self.active:
            self.request_cancel(self.active.id)
        else:
            self.model.set_direction(**candidate)
            if not self.model.quantity:
                self.transition = None

    def continue_transition(self, order_id, *, reference_price):
        self._new(order_id)
        if not self.transition:
            raise ValueError('no pending trend transition')
        price = positive(reference_price)
        if not self.model.quantity:
            self.model.set_direction(**self.transition)
            self.model.supersede_reduction('trend transition completed flat')
            self.transition = None
            return None
        if not self.costs.executable(self.model.quantity, price):
            raise ValueError('exit below minimum order; explicit resolution required')
        self.model.set_direction(**self.transition)
        self.model.supersede_reduction('four-hour trend reversal full exit')
        order = CyclingOrder(order_id, 'exit', self.model.quantity,
                             self.model.position_side, None, None)
        self.orders[order_id] = order
        return order

    def checkpoint(self):
        from .cycling_checkpoint import checkpoint
        return checkpoint(self)

    @classmethod
    def restore(cls, payload):
        from .cycling_checkpoint import restore
        return restore(payload)

    def reconcile(self, *, side, quantity, average, open_orders):
        """Compare an independently obtained position/open-order snapshot.

        Missing executions must first be replayed. This never overwrites the
        ledger to make a discrepancy disappear or clears an execution fault.
        """
        expected = {o.id: dict(filled=str(o.filled), status=o.status)
                    for o in self.orders.values() if o.status in ('open', 'cancel_pending')}
        normalized = {key: dict(filled=str(dec(value['filled'])), status=value['status'])
                      for key, value in open_orders.items()}
        matches_orders = (set(expected) == set(normalized) and all(
            dec(expected[k]['filled']) == dec(normalized[k]['filled']) and
            expected[k]['status'] == normalized[k]['status'] for k in expected))
        if (side != self.model.position_side or dec(quantity) != self.model.quantity or
                (None if average is None else dec(average)) != self.model.average or not matches_orders):
            self.restart_required = True
            raise ValueError('position/order mismatch; reconciliation remains required')
        if self.locked:
            raise ValueError('execution fault requires external recovery')
        self.restart_required = False
