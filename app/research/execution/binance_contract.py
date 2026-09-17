"""Pure BTCUSDC one-way preflight and strict REST query parsing; no transport.

Passing public filters is not account/risk approval. Exchange timestamps are
metadata, never used as the durable journal's reconciled receipt sequence.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


def decimal(value):
    if isinstance(value, (bool, float)):
        raise ValueError('decimal string or integer required')
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError('invalid decimal') from None
    if not result.is_finite():
        raise ValueError('nonfinite decimal')
    return result


@dataclass(frozen=True)
class Contract:
    raw: dict

    def __post_init__(self):
        if (self.raw.get('symbol'), self.raw.get('contractType'), self.raw.get('marginAsset')) != ('BTCUSDC', 'PERPETUAL', 'USDC'):
            raise ValueError('wrong contract')
        filters = self.raw['filters']
        names = [f['filterType'] for f in filters]
        if len(set(names)) != len(names):
            raise ValueError('duplicate filters')
        required = {'PRICE_FILTER', 'LOT_SIZE', 'MARKET_LOT_SIZE', 'MIN_NOTIONAL', 'PERCENT_PRICE'}
        if not required <= set(names):
            raise ValueError('missing filters')

    def filter(self, name):
        return next(f for f in self.raw['filters'] if f['filterType'] == name)

    def check(self, *, order_type, side, quantity, mark_price, price=None,
              reduce_only=False, position_quantity=Decimal('0'), position_mode='ONE_WAY'):
        """Raise on rejection; never round up or infer an unknown account mode.

        reduce-only exempts minimum notional, but still requires a known opposite
        position and quantity cap. Freshness, balance, fees and loss limits are
        independent mandatory checks in the caller.
        """
        if self.raw['status'] != 'TRADING' or position_mode != 'ONE_WAY':
            raise ValueError('unsupported trading state or position mode')
        if order_type not in ('LIMIT', 'MARKET') or side not in ('BUY', 'SELL') or type(reduce_only) is not bool:
            raise ValueError('unsupported order')
        qty, mark, position = map(decimal, (quantity, mark_price, position_quantity))
        if qty <= 0 or mark <= 0:
            raise ValueError('nonpositive quantity or mark')
        for name in (('LOT_SIZE', 'MARKET_LOT_SIZE') if order_type == 'MARKET' else ('LOT_SIZE',)):
            f = self.filter(name)
            minimum, maximum, step = map(decimal, (f['minQty'], f['maxQty'], f['stepSize']))
            if minimum < 0 or maximum < minimum or step <= 0:
                raise ValueError('invalid quantity filter')
            if not minimum <= qty <= maximum or (qty - minimum) % step:
                raise ValueError(name)
        if reduce_only and (position == 0 or (position > 0) == (side == 'BUY') or qty > abs(position)):
            raise ValueError('exit increases or reverses position')
        reference = mark
        if order_type == 'LIMIT':
            reference = decimal(price)
            f = self.filter('PRICE_FILTER')
            low, high, tick = map(decimal, (f['minPrice'], f['maxPrice'], f['tickSize']))
            if min(low, high, tick) < 0 or reference <= 0:
                raise ValueError('invalid price filter')
            if (low and reference < low) or (high and reference > high) or (tick and (reference-low) % tick):
                raise ValueError('PRICE_FILTER')
            f = self.filter('PERCENT_PRICE')
            down, up = decimal(f['multiplierDown']), decimal(f['multiplierUp'])
            if not 0 < down <= up:
                raise ValueError('invalid percent filter')
            if (side == 'BUY' and reference > mark*up) or (side == 'SELL' and reference < mark*down):
                raise ValueError('PERCENT_PRICE')
        elif price is not None:
            raise ValueError('market order must not carry a limit price')
        minimum_notional = decimal(self.filter('MIN_NOTIONAL')['notional'])
        if minimum_notional <= 0:
            raise ValueError('invalid minimum notional')
        if not reduce_only and qty*reference < minimum_notional:
            raise ValueError('MIN_NOTIONAL')
        return qty


@dataclass(frozen=True)
class OrderObservation:
    order_id: int
    client_id: str
    status: str
    quantity: Decimal
    executed: Decimal
    average_price: Decimal
    exchange_updated_ms: int
    observed_ms: int


def parse_query(payload, *, client_id, side, quantity, order_type, reduce_only, observed_ms):
    """Only full REST query-shaped evidence, not ACK/test-success or stream data."""
    expected = dict(symbol='BTCUSDC', clientOrderId=client_id, side=side,
                    origQty=decimal(quantity), type=order_type, reduceOnly=reduce_only, positionSide='BOTH')
    if side not in ('BUY', 'SELL') or order_type not in ('LIMIT', 'MARKET') or type(reduce_only) is not bool:
        raise ValueError('invalid expected order')
    for key, value in expected.items():
        actual = decimal(payload[key]) if key == 'origQty' else payload[key]
        if actual != value or (key == 'reduceOnly' and type(actual) is not bool):
            raise ValueError('order identity mismatch: ' + key)
    status = payload['status']
    # Preserve raw meaning in the input; normalize STP expiry to terminal EXPIRED.
    if status == 'EXPIRED_IN_MATCH':
        status = 'EXPIRED'
    if status not in {'NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'EXPIRED', 'REJECTED'}:
        raise ValueError('unsupported status')
    qty, executed, average = expected['origQty'], decimal(payload['executedQty']), decimal(payload['avgPrice'])
    if qty <= 0 or not 0 <= executed <= qty or average < 0 or (executed > 0 and average <= 0):
        raise ValueError('invalid fill')
    if (status == 'FILLED' and executed != qty) or (status == 'NEW' and executed != 0) or (status == 'PARTIALLY_FILLED' and not 0 < executed < qty):
        raise ValueError('status disagrees with fill')
    order_id, updated = payload['orderId'], payload['updateTime']
    if any(type(v) is not int or v < 0 for v in (order_id, updated, observed_ms)) or order_id == 0:
        raise ValueError('invalid order id or time')
    return OrderObservation(order_id, client_id, status, qty, executed, average, updated, observed_ms)
