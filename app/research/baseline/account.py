"""Linear-contract ledger with fixed quantity between entry and exit."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math


def round_step(value: float, step: float, up: bool = False) -> float:
    if not math.isfinite(value) or value < 0 or not math.isfinite(step) or step <= 0:
        raise ValueError('invalid rounding input')
    result = (Decimal(str(value)) / Decimal(str(step))).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)
    return float(result * Decimal(str(step)))


@dataclass(frozen=True)
class Costs:
    fee_bps: float = 5
    slippage_bps: float = 2
    funding_bps_8h: float = 0
    tick: float = .1

    def fill(self, reference: float, order_side: int) -> float:
        if order_side not in (-1, 1) or not math.isfinite(reference) or reference <= 0:
            raise ValueError('invalid fill input')
        slipped = reference * (1 + order_side * self.slippage_bps / 10000)
        return round_step(slipped, self.tick, up=order_side == 1)


class Account:
    def __init__(self, initial: float):
        if not math.isfinite(initial) or initial <= 0:
            raise ValueError('invalid initial capital')
        self.initial = initial
        self.balance = initial
        self.quantity = 0.0
        self.average = 0.0
        self.realized = 0.0
        self.fees = 0.0
        self.funding = 0.0
        self.events = []

    def equity(self, price: float) -> float:
        return self.balance + self.quantity * (price - self.average)

    def record(self, time, kind, **values):
        expected = self.initial + self.realized - self.fees - self.funding
        if not math.isclose(self.balance, expected, abs_tol=1e-8) or not math.isfinite(self.balance):
            raise ValueError('ledger identity failed')
        self.events.append(dict(time=str(time), kind=kind, balance=self.balance,
                                quantity=self.quantity, average=self.average, **values))

    def enter(self, time, side: int, qty: float, price: float, fee_bps: float, reason='signal'):
        if self.quantity or side not in (-1, 1) or not all(math.isfinite(v) and v > 0 for v in (qty, price)):
            raise ValueError('invalid entry')
        fee = qty * price * fee_bps / 10000
        self.quantity = side * qty
        self.average = price
        self.fees += fee
        self.balance -= fee
        self.record(time, 'entry', side=side, qty=qty, price=price, fee=fee, reason=reason)

    def close(self, time, price: float, fee_bps: float, reason: str):
        if not self.quantity or not math.isfinite(price) or price <= 0:
            raise ValueError('invalid exit')
        signed_quantity = self.quantity
        pnl = signed_quantity * (price - self.average)
        fee = abs(signed_quantity) * price * fee_bps / 10000
        self.realized += pnl
        self.fees += fee
        self.balance += pnl - fee
        self.quantity = 0.0
        self.average = 0.0
        self.record(time, 'exit', side=-1 if signed_quantity > 0 else 1, qty=abs(signed_quantity),
                    price=price, fee=fee, pnl=pnl, reason=reason)

    def pay_funding(self, time, mark: float, bps: float):
        if not self.quantity or bps == 0:
            return
        amount = abs(self.quantity) * mark * bps / 10000
        self.funding += amount
        self.balance -= amount
        self.record(time, 'funding', amount=amount, mark=mark)


def replay(events: list[dict], initial: float) -> dict:
    """Independent cash/position event replay, not Account method reuse."""
    cash, quantity, entry_price = initial, 0.0, 0.0
    for event in events:
        if event['kind'] == 'entry':
            if quantity:
                raise ValueError('duplicate position in replay')
            quantity = event['side'] * event['qty']
            entry_price = event['price']
            cash -= event['fee']
        elif event['kind'] == 'exit':
            if not quantity or not math.isclose(abs(quantity), event['qty'], abs_tol=1e-12):
                raise ValueError('replay close quantity mismatch')
            cash += quantity * event['price'] - quantity * entry_price - event['fee']
            quantity, entry_price = 0.0, 0.0
        elif event['kind'] == 'funding':
            cash -= event['amount']
        else:
            raise ValueError('unknown ledger event')
        if not all(math.isclose(a, b, abs_tol=1e-7, rel_tol=0) for a, b in
                   [(cash, event['balance']), (quantity, event['quantity']), (entry_price, event['average'])]):
            raise ValueError('independent replay mismatch')
    return dict(status='PASS', checked_events=len(events), balance=cash, quantity=quantity)
