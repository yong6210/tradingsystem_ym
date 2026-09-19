"""Displayed dated-carry components, never a net-profit or fill forecast."""
from decimal import Decimal as D


def displayed_vwap(levels, quantity):
    remaining, quote = quantity, D(0)
    for price, size in levels:
        take = min(remaining, D(size))
        quote += take * D(price)
        remaining -= take
        if not remaining:
            return quote / quantity
    return None


def check_book(book):
    for key, sign in [('bids', -1), ('asks', 1)]:
        levels = book[key]
        if not levels or any(D(p) <= 0 or D(q) <= 0 for p, q in levels):
            raise ValueError('empty/nonpositive book')
        if any(sign * (D(b[0]) - D(a[0])) <= 0 for a, b in zip(levels, levels[1:])):
            raise ValueError('unordered/duplicate book')
    if D(book['bids'][0][0]) >= D(book['asks'][0][0]):
        raise ValueError('locked/crossed book')


def entry_components(spot, future, quantity=D('.001')):
    if quantity <= 0:
        raise ValueError('quantity must be positive')
    check_book(spot)
    check_book(future)
    s = displayed_vwap(spot['asks'], quantity)
    f = displayed_vwap(future['bids'], quantity)
    if s is None or f is None:
        return dict(status='INSUFFICIENT_DISPLAYED_DEPTH')
    return dict(status='DISPLAYED_COMPONENT_ONLY', quantity_btc=str(quantity),
        spot_buy_vwap=str(s), future_sell_vwap=str(f), spot_quote_usdt=str(quantity * s),
        futures_notional_usdt=str(quantity * f), initial_basis_component_usdt=str(quantity * (f - s)),
        initial_basis_bps=str((f / s - 1) * 10000),
        net_profit_usdc=None, actual_fills_verified=False)


def terminal_components(quantity, spot_entry, future_entry, spot_exit, future_settlement, costs):
    """Exact linear cash-flow identity; caller must supply actual net matched quantity."""
    initial = quantity * (future_entry - spot_entry)
    mismatch = quantity * (spot_exit - future_settlement)
    return initial, mismatch, initial + mismatch - costs
