"""Conditional displayed basis budgets, not carry account profitability."""
from decimal import Decimal as D
from app.research.diagnostics.dated_carry import check_book


def quote_cost(levels, quantity):
    if quantity <= 0: raise ValueError('quantity must be positive')
    remaining, total = quantity, D(0)
    for p, q in levels:
        p, q = D(p), D(q)
        if p <= 0 or q <= 0: raise ValueError('nonpositive level')
        take = min(q, remaining)
        total += take*p
        remaining -= take
        if not remaining: return total
    return None


def capital_rows(spot, future, cash=D(1000), step=D('.001'), entry_fee_rate=D('.001')):
    check_book(spot); check_book(future)
    if cash <= 0 or step <= 0 or not D(0) <= entry_fee_rate < 1: raise ValueError('invalid budget')
    rows = []
    # Best ask supplies an upper quantity limit; depth may reduce feasibility.
    upper = int(cash/(D(spot['asks'][0][0])*step))
    for lots in range(1, upper+2):
        q = step*lots
        a = quote_cost(spot['asks'], q); f = quote_cost(future['bids'], q)
        row = dict(lots=lots, quantity_btc=str(q))
        if a is None or f is None:
            rows.append(dict(row, status='INSUFFICIENT_DISPLAYED_DEPTH'))
            continue
        basis, fee, remaining = f-a, a*entry_fee_rate, cash-a
        values = dict(spot_quote_usdt=a, future_quote_usdt=f, basis_component_usdt=basis,
            spot_entry_fee_reference_usdt=fee, basis_after_entry_fee_only_usdt=basis-fee,
            cash_after_spot_before_fees_usdt=remaining, cash_after_spot_entry_fee_usdt=remaining-fee,
            cash_to_short_notional_ratio_before_fees=remaining/f,
            cash_to_short_notional_ratio_after_entry_fee=(remaining-fee)/f)
        rows.append(dict(row,status='CASH_REFERENCE_ONLY',**{k:str(v) for k,v in values.items()},
            spot_only_cash_feasible=a<=cash, spot_plus_entry_fee_cash_feasible=a+fee<=cash,
            full_entry_notional_cash_reference_feasible=a+f<=cash,
            full_notional_plus_entry_fee_reference_feasible=a+f+fee<=cash))
    return rows
