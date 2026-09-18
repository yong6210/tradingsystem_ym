"""Apply a reported taker rate without changing other execution assumptions."""
from dataclasses import replace
from decimal import Decimal, InvalidOperation

from app.research.baseline.account import Costs


def reported_taker_costs(context, reference=Costs()):
    if (context.get('exchange') != 'Binance' or context.get('symbol') != 'BTCUSDC'
            or context.get('instrument') != 'PERPETUAL'):
        raise ValueError('BTCUSDC perpetual account context required')
    fees = context['fees_per_fill']
    if fees.get('basis') != 'ABSOLUTE_EXECUTED_NOTIONAL':
        raise ValueError('executed notional fee basis required')
    values = fees['taker']
    parsed = {}
    for key in ('percent','basis_points','fraction'):
        value = values[key]
        if isinstance(value,bool): raise ValueError('numeric fee required')
        try: number = Decimal(str(value))
        except InvalidOperation as exc: raise ValueError('numeric fee required') from exc
        if not number.is_finite() or number < 0:
            raise ValueError('finite nonnegative fee required')
        parsed[key] = number
    if not parsed['percent']/100 == parsed['basis_points']/10000 == parsed['fraction']:
        raise ValueError('fee units disagree')
    return replace(reference,fee_bps=float(parsed['basis_points']))
