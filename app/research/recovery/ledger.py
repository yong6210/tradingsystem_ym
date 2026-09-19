"""Actual fills, risk reservations and two independent break-even calculations."""
from dataclasses import dataclass, field
from decimal import Decimal

from .models import Costs, dec, positive


@dataclass
class Lot:
    id: str
    quantity: Decimal
    entry: Decimal
    stop: Decimal
    kind: str
    event_id: str
    zone_key: str
    allocated_cost: Decimal = Decimal(0)


@dataclass
class Order:
    id: str
    created_ms: int
    quantity: Decimal
    kind: str
    reason: str
    limit: Decimal | None = None
    stop: Decimal | None = None
    event_id: str = ""
    zone_key: str = ""
    targets: dict = field(default_factory=dict)
    filled: Decimal = Decimal(0)
    status: str = "open"
    expires_ms: int | None = None

    @property
    def remaining(self):
        return max(dec(0), self.quantity - self.filled)

    @property
    def active(self):
        return self.status in ("open", "cancel_pending") and self.remaining > 0

    @property
    def increasing(self):
        return self.kind != "reduce"


class Ledger:
    def __init__(self, equity, side, costs: Costs):
        self.start_equity = positive(equity)
        self.side = side
        self.costs = costs
        self.cash = self.start_equity
        self.lots: dict[str, Lot] = {}
        self.orders: dict[str, Order] = {}
        self.seen_fills = {}
        self.seen_funding = {}
        self.realized_gross = dec(0)
        self.realized_losses = dec(0)
        self.paid_costs = dec(0)
        self.net_costs = dec(0)
        self.add_events: set[str] = set()
        self.rows = []

    @property
    def quantity(self):
        return sum((x.quantity for x in self.lots.values()), dec(0))

    @property
    def average(self):
        q = self.quantity
        return sum((x.quantity * x.entry for x in self.lots.values()), dec(0)) / q if q else None

    @property
    def settled(self):
        return not self.quantity and not any(o.active for o in self.orders.values())

    def risk_used(self):
        risk = self.realized_losses + self.paid_costs
        risk += sum((lot.quantity * self.costs.loss(lot.entry, lot.stop, self.side, False)
                     for lot in self.lots.values()), dec(0))
        risk += sum((o.remaining * self.costs.loss(o.limit, o.stop, self.side)
                     for o in self.orders.values() if o.active and o.increasing), dec(0))
        return risk

    def break_evens(self):
        q = self.quantity
        if not q:
            return {"position": None, "campaign": None}
        # Required pre-slippage executable quote; tick rounding remains an estimate.
        denominator = q * (1 - self.side * self.costs.slippage) * (self.side - self.costs.fee)
        base = self.side * q * self.average
        allocated = sum((lot.allocated_cost for lot in self.lots.values()), dec(0))
        position = (base + allocated) / denominator
        campaign = (base - (self.cash - self.start_equity)) / denominator
        return {"position": position if position > 0 else None,
                "campaign": campaign if campaign > 0 else None}

    def apply_fill(self, fill_id, order_id, quantity, price, fee, time_ms):
        qty, price, fee = positive(quantity), positive(price), dec(fee)
        signature = (order_id, qty, price, fee, time_ms)
        if fill_id in self.seen_fills:
            if self.seen_fills[fill_id] != signature:
                raise ValueError("conflicting duplicate fill")
            return False
        o = self.orders[order_id]
        if fee < 0 or qty > o.remaining or time_ms < o.created_ms:
            raise ValueError("invalid fill quantity/cost/time")
        # A late execution after cancellation acknowledgment is still real exposure.
        if not o.increasing:
            available = sum((min(self.lots[k].quantity, n) for k, n in o.targets.items() if k in self.lots), dec(0))
            if qty > available:
                raise ValueError("reduce fill exceeds attributed position")
        gross = dec(0)
        if o.increasing:
            key = o.id
            if key in self.lots:
                lot = self.lots[key]
                lot.entry = (lot.quantity * lot.entry + qty * price) / (lot.quantity + qty)
                lot.quantity += qty
                lot.allocated_cost += fee
            else:
                self.lots[key] = Lot(key, qty, price, o.stop, o.kind, o.event_id, o.zone_key, fee)
            if o.kind == "add":
                self.add_events.add(o.event_id)
        else:
            left = qty
            for key in list(o.targets):
                if not left:
                    break
                lot = self.lots.get(key)
                if lot is None:
                    continue
                part = min(left, o.targets[key], lot.quantity)
                if not part:
                    continue
                pnl = self.side * part * (price - lot.entry)
                gross += pnl
                self.realized_losses += max(dec(0), -pnl)
                lot.allocated_cost *= (lot.quantity - part) / lot.quantity
                lot.quantity -= part
                o.targets[key] -= part
                left -= part
                if not lot.quantity:
                    del self.lots[key]
        self.realized_gross += gross
        self.paid_costs += fee
        self.net_costs += fee
        self.cash += gross - fee
        o.filled += qty
        if not o.remaining:
            o.status = "filled"
        self.seen_fills[fill_id] = signature
        self.rows.append(dict(type="fill", time_ms=time_ms, fill_id=fill_id, order_id=o.id,
                              kind=o.kind, reason=o.reason, qty=qty, price=price, fee=fee,
                              gross=gross, cash=self.cash, position_qty=self.quantity))
        self.audit()
        return True

    def funding(self, event_id, amount, time_ms):
        # Positive amount is a cash debit. Receipts cannot refill the risk budget.
        amount = dec(amount)
        signature = (amount, time_ms)
        if event_id in self.seen_funding:
            if self.seen_funding[event_id] != signature:
                raise ValueError("conflicting funding event")
            return False
        q = self.quantity
        if q:
            for lot in self.lots.values():
                lot.allocated_cost += amount * lot.quantity / q
        self.cash -= amount
        self.net_costs += amount
        self.paid_costs += max(dec(0), amount)
        self.seen_funding[event_id] = signature
        self.rows.append(dict(type="funding", event_id=event_id, time_ms=time_ms, amount=amount, cash=self.cash))
        self.audit()
        return True

    def audit(self):
        if abs(self.cash - (self.start_equity + self.realized_gross - self.net_costs)) > dec("1e-20"):
            raise AssertionError("cash conservation failure")
        if any(x.quantity <= 0 for x in self.lots.values()):
            raise AssertionError("invalid residual lot")
