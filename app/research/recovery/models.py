"""Explicit inputs and decimal arithmetic for linear, single-symbol contracts."""
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Any


def dec(value: Any) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("non-finite number")
    return result


def positive(value: Any) -> Decimal:
    result = dec(value)
    if result <= 0:
        raise ValueError("expected positive number")
    return result


def require_flags(*values):
    if any(type(value) is not bool for value in values):
        raise ValueError("state flags must be JSON booleans")


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return max(dec(0), (value / step).to_integral_value(rounding=ROUND_FLOOR) * step)


def jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return jsonable(asdict(value))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return value


@dataclass(frozen=True)
class Policy:
    campaign_fraction: Decimal = Decimal("0.01")
    add_fraction: Decimal = Decimal("0.25")
    buffer_atr: Decimal = Decimal("0.10")
    minimum_rr: Decimal = Decimal("1.5")
    max_adds: int = 2
    observation_bars: int = 5
    confirmation_ms: int = 540000
    late_ms: int = 10000

    def __post_init__(self):
        for name in ("campaign_fraction", "add_fraction", "buffer_atr", "minimum_rr"):
            object.__setattr__(self, name, positive(getattr(self, name)))
        if self.campaign_fraction > 1 or self.add_fraction > 1:
            raise ValueError("invalid risk fraction")
        for name in ("max_adds", "observation_bars", "confirmation_ms", "late_ms"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) <= 0:
                raise ValueError("invalid policy count/time")


@dataclass(frozen=True)
class Costs:
    fee: Decimal
    slippage: Decimal
    tick: Decimal
    step: Decimal
    minimum_qty: Decimal
    minimum_notional: Decimal

    def __post_init__(self):
        for name in ("fee", "slippage", "tick", "step", "minimum_qty", "minimum_notional"):
            object.__setattr__(self, name, dec(getattr(self, name)))
        if min(self.fee, self.slippage, self.minimum_notional) < 0:
            raise ValueError("negative costs")
        if max(self.fee, self.slippage) >= 1 or min(self.tick, self.step, self.minimum_qty) <= 0:
            raise ValueError("invalid costs/order rules")

    def exit_price(self, price: Decimal, side: int) -> Decimal:
        # Conservative adverse price for risk estimates; actual fills are separate.
        raw = price * (1 - side * self.slippage)
        rounded = floor_step(raw, self.tick)
        return rounded if side == 1 or rounded == raw else rounded + self.tick

    def loss(self, entry: Decimal, stop: Decimal, side: int, entry_fee=True) -> Decimal:
        out = self.exit_price(stop, side)
        return max(dec(0), side * (entry - out)) + out * self.fee + (entry * self.fee if entry_fee else 0)

    def executable(self, qty: Decimal, price: Decimal) -> bool:
        return qty >= self.minimum_qty and qty * price >= self.minimum_notional


@dataclass(frozen=True)
class Zone:
    id: str
    version: int
    low: Decimal
    high: Decimal
    available_ms: int
    evidence: str
    valid: bool = True
    structural_close_ms: int | None = None

    def __post_init__(self):
        object.__setattr__(self, "low", positive(self.low))
        object.__setattr__(self, "high", positive(self.high))
        require_flags(self.valid)
        if self.low >= self.high or not self.id or not self.evidence or self.version < 1:
            raise ValueError("invalid zone")

    @property
    def key(self):
        return f"{self.id}:{self.version}"

    def bounds(self, side: int):
        return (self.low, self.high) if side == 1 else (-self.high, -self.low)


@dataclass(frozen=True)
class Bar:
    end_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    received_ms: int

    def __post_init__(self):
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, positive(getattr(self, name)))
        if self.end_ms % 60000 or self.received_ms < self.end_ms:
            raise ValueError("bar must be completed and UTC minute-aligned")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError("invalid OHLC")

    def normalized(self, side: int):
        return (self.low, self.high, self.close) if side == 1 else (-self.high, -self.low, -self.close)


@dataclass(frozen=True)
class Quote:
    time_ms: int
    bid: Decimal
    ask: Decimal
    max_total_qty: Decimal
    margin_room_qty: Decimal
    liquidity_qty: Decimal
    execution_ok: bool
    funding_known: bool

    def __post_init__(self):
        require_flags(self.execution_ok, self.funding_known)
        for name in ("bid", "ask", "max_total_qty", "margin_room_qty", "liquidity_qty"):
            object.__setattr__(self, name, dec(getattr(self, name)))
        if self.bid <= 0 or self.ask < self.bid or min(self.max_total_qty, self.margin_room_qty, self.liquidity_qty) < 0:
            raise ValueError("invalid quote/capacity")

    def entry(self, side):
        return self.ask if side == 1 else self.bid

    def exit(self, side):
        return self.bid if side == 1 else self.ask


@dataclass(frozen=True)
class Plan:
    id: str
    side: int
    created_ms: int
    support: Zone
    target: Zone
    stop: Decimal
    initial_qty: Decimal
    reason: str
    # (limit price, quantity), declared before the first order; comparison only.
    splits: tuple = ()
    expires_ms: int | None = None

    def __post_init__(self):
        object.__setattr__(self, "stop", positive(self.stop))
        object.__setattr__(self, "initial_qty", positive(self.initial_qty))
        object.__setattr__(self, "splits", tuple((positive(p), positive(q)) for p, q in self.splits))
        if self.side not in (-1, 1) or not self.reason or not self.id:
            raise ValueError("missing independent entry thesis")
        if self.expires_ms is not None and self.expires_ms <= self.created_ms:
            raise ValueError("plan expiry must follow creation")
        if self.splits and self.expires_ms is None:
            raise ValueError("planned splits require explicit cancellation deadline")
        if any(z.available_ms > self.created_ms or not z.valid for z in (self.support, self.target)):
            raise ValueError("future/invalid plan zone")
