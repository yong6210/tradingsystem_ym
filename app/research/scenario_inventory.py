"""Offline linear-perpetual research primitives. No exchange or order API access."""
from dataclasses import dataclass
import math


@dataclass
class PerpetualAccount:
    initial: float = 10_000.0
    balance: float = 10_000.0
    side: int = 0
    qty: float = 0.0
    average: float = 0.0
    realized: float = 0.0
    fees: float = 0.0
    funding_paid: float = 0.0

    def equity(self, price):
        return self.balance + self.side * self.qty * (price - self.average)

    def add(self, side, qty, price, fee_rate=0.0):
        if side not in (-1, 1) or qty <= 0 or price <= 0:
            raise ValueError('invalid fill')
        if self.qty and self.side != side:
            raise ValueError('close the old side before switching')
        self.average = (self.average * self.qty + price * qty) / (self.qty + qty)
        self.qty += qty
        self.side = side
        self._fee(qty * price * fee_rate)
        self.check(price)

    def reduce(self, qty, price, fee_rate=0.0):
        if qty < 0 or price <= 0:
            raise ValueError('invalid reduction')
        qty = min(qty, self.qty)
        pnl = self.side * qty * (price - self.average)
        self.balance += pnl
        self.realized += pnl
        self.qty -= qty
        self._fee(qty * price * fee_rate)
        if self.qty < 1e-10:
            self.qty = 0.0
            self.average = 0.0
            self.side = 0
        self.check(price)
        return pnl

    def _fee(self, amount):
        self.fees += amount
        self.balance -= amount

    def funding(self, price, signed_rate):
        amount = self.side * self.qty * price * signed_rate
        self.funding_paid += amount
        self.balance -= amount
        self.check(price)

    def check(self, price):
        expected = self.initial + self.realized - self.fees - self.funding_paid
        if not math.isclose(self.balance, expected, abs_tol=1e-7):
            raise AssertionError('balance does not reconcile')
        if not math.isfinite(self.equity(price)) or self.qty < 0:
            raise AssertionError('invalid account')

    def liquidation_price(self, maintenance_rate):
        if not self.qty:
            return None
        if self.side == 1:
            return (self.qty * self.average - self.balance) / (self.qty * (1-maintenance_rate))
        return (self.balance + self.qty * self.average) / (self.qty * (1+maintenance_rate))


@dataclass
class PassiveOrder:
    side: int
    qty: float
    price: float
    created: int
    reason: str
    reduce_only: bool = False
    remaining: float | None = None
    admitted: bool = False
    counted: bool = False
    fills: int = 0

    def __post_init__(self):
        self.remaining = self.qty


def passive_fill(order, bar, index, *, ttl=3, penetration_bps=1., fill_fraction=1., participation=.001):
    """Order is posted after its signal bar. OHLC crossing is only a fill proxy.

    Crossing the next open rejects admission conservatively; a strict penetration
    is required rather than counting a mere touch. No same-bar placement/fill.
    """
    if index <= order.created:
        return 0., 'waiting'
    if index > order.created + ttl:
        return 0., 'expired'
    if not order.admitted:
        if order.side * (order.price-bar.o) >= 0:
            return 0., 'post_only_rejected'
        order.admitted = True
    barrier = order.price * (1-order.side * penetration_bps/10000)
    crossed = bar.l < barrier if order.side == 1 else bar.h > barrier
    if not crossed:
        return 0., 'waiting'
    qty = min(order.remaining, order.qty*fill_fraction, max(0.,bar.v)*participation)
    return max(0.,qty), 'eligible'


def addition_capacity(account, side, price, stop, cycle_balance, *, max_exposure, leverage, risk_fraction):
    equity = account.equity(price)
    if equity <= 0 or side*(price-stop) <= 0:
        return 0.
    exposure_qty = max(0., min(max_exposure,leverage)*equity/price-account.qty)
    loss_room = cycle_balance*risk_fraction + account.equity(stop)-cycle_balance
    risk_qty = max(0.,loss_room)/(side*(price-stop))
    return min(exposure_qty,risk_qty)


def recovery_quantity(account, side, price, target, cycle_balance, goal):
    move = side*(target-price)
    if move <= 0:
        return math.inf
    projected = account.equity(target)-cycle_balance
    return max(0., (goal-projected)/move)
