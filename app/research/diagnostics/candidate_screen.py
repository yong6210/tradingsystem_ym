"""Frozen event rules and contract-size diagnostics; not a trading engine."""
from decimal import Decimal, ROUND_CEILING

import numpy as np
import pandas as pd


def candidate_conditions(bank: dict, model: str) -> pd.DataFrame:
    """Return conditions at completed candle availability, before event thinning."""
    period = {'S01': 240, 'S02': 60, 'S04': 15, 'S05': 15, 'S07': 60, 'S08': 60}[model]
    frame = bank[period]
    higher = bank[240].reindex(frame.index, method='ffill')
    valid = frame.atr.notna() & higher.ema80.notna() & higher.er.notna()
    if model == 'S01':
        spread = (frame.ema20 - frame.ema80) / frame.atr
        long = (spread > .5) & (frame.c > frame.ema20) & (frame.er > .2)
        short = (spread < -.5) & (frame.c < frame.ema20) & (frame.er > .2)
    elif model in ('S02', 'S08'):
        long = (frame.c > frame.high24 + .1 * frame.atr) & (frame.volume_ratio > 1)
        short = (frame.c < frame.low24 - .1 * frame.atr) & (frame.volume_ratio > 1)
        valid &= frame.high24.notna() & frame.low24.notna() & frame.volume_ratio.notna()
        if model == 'S08':
            ratio = frame.atr / frame.c
            cutoff = ratio.shift(2).rolling(120).quantile(.25)
            squeezed = ratio.shift(1) < cutoff
            valid &= cutoff.notna()
            long &= squeezed
            short &= squeezed
    elif model == 'S04':
        valid &= frame.z.notna()
        long = (higher.er < .25) & (frame.z < -2.4)
        short = (higher.er < .25) & (frame.z > 2.4)
    elif model == 'S05':
        valid &= frame.z.notna() & frame.z.shift().notna()
        long = (higher.er < .25) & (frame.z.shift() < -2.4) & (frame.z >= -1.5)
        short = (higher.er < .25) & (frame.z.shift() > 2.4) & (frame.z <= 1.5)
    else:
        # Previous breakout's channel stays fixed at its previously available value.
        upper, lower = frame.high24.shift(), frame.low24.shift()
        valid &= upper.notna() & lower.notna() & frame.c.shift().notna()
        inside = (frame.c <= upper) & (frame.c >= lower)
        long = (frame.c.shift() < lower) & inside
        short = (frame.c.shift() > upper) & inside
    side = pd.Series(np.select([long & valid, short & valid], [1, -1], 0), index=frame.index)
    event = side.ne(0) & side.ne(side.shift(fill_value=0)) & valid
    return pd.DataFrame({'side': side, 'event': event, 'valid': valid,
                         'close': frame.c, 'atr': frame.atr}, index=frame.index)


def minimum_order(price: float, minimum_qty: float, step: float, notional: float) -> float:
    """Round required quantity up using decimal contract arithmetic."""
    if not all(np.isfinite(x) and x > 0 for x in (price, minimum_qty, step, notional)):
        raise ValueError('positive finite contract values required')
    p, q, increment, n = map(lambda x: Decimal(str(x)), (price, minimum_qty, step, notional))
    units = (max(q, n / p) / increment).to_integral_value(rounding=ROUND_CEILING)
    return float(units * increment)


def feasibility(entry: float, decision_close: float, atr: float, side: int,
                stop_atr: float, settings: dict) -> dict:
    """Fixed-equity proxy, with no account path or order-fill probability."""
    if side not in (-1, 1) or not all(np.isfinite(v) and v > 0 for v in (entry, decision_close, atr, stop_atr)):
        raise ValueError('invalid feasibility input')
    qty = minimum_order(entry, settings['minimum_qty_btc'], settings['qty_step_btc'], settings['minimum_notional_usdc'])
    stop = decision_close - side * stop_atr * atr
    distance = side * (entry - stop)
    valid_stop = stop > 0 and distance > 0
    notional = qty * entry
    loss = qty * distance if valid_stop else None
    slip = settings['slippage_bps_per_side'] / 10000
    fee = settings['taker_bps_per_side'] / 10000
    cost = qty * ((entry + stop) * slip + (entry * (1 + side * slip) + stop * (1 - side * slip)) * fee) if valid_stop else None
    cap = settings['equity_usdc'] * settings['exposure_multiple']
    risk = settings['equity_usdc'] * settings['risk_fraction']
    gross_ok = valid_stop and notional <= cap + 1e-10 and loss <= risk + 1e-10
    net_ok = gross_ok and loss + cost <= risk + 1e-10
    reason = ('invalid_stop' if not valid_stop else 'notional_cap' if notional > cap + 1e-10
              else 'stop_risk' if loss > risk + 1e-10 else 'cost_reserve' if not net_ok else 'eligible_proxy')
    return dict(minimum_qty=qty, minimum_notional=notional, planned_price_loss=loss,
                cost_reserve=cost, gross_eligible=bool(gross_ok), cost_eligible=bool(net_ok),
                feasibility_reason=reason)


def independent_interval(rows: list[dict], start, end, block_days: int, repetitions: int, seed: int):
    """Separate pandas grouping plus loop resampling to check vectorized estimator."""
    if not rows:
        return None
    dates = pd.date_range(start, end, freq='D', inclusive='left')
    if len(dates) < block_days:
        return None
    frame = pd.DataFrame(rows)
    frame['day'] = pd.to_datetime(frame.decision_time, utc=True).dt.floor('D')
    grouped = frame.groupby('day').excess_bps.agg(['sum', 'count']).reindex(dates, fill_value=0)
    sums, counts = grouped['sum'].tolist(), grouped['count'].tolist()
    rng = np.random.Generator(np.random.PCG64(seed))
    samples = []
    blocks = (len(dates) + block_days - 1) // block_days
    for _ in range(repetitions):
        starts = rng.integers(0, len(dates) - block_days + 1, size=blocks)
        selected = []
        for first in starts:
            selected.extend(range(int(first), int(first) + block_days))
        selected = selected[:len(dates)]
        count = sum(counts[i] for i in selected)
        if count:
            samples.append(sum(sums[i] for i in selected) / count)
    return np.quantile(samples, [.025, .975]).tolist() if samples else None
