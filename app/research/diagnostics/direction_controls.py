"""Fixed direction controls for T0; diagnostic accounts, never selected models."""
from datetime import date, timedelta
from decimal import Decimal
import math

import numpy as np

MODELS = ('T0', 'LONG', 'SHORT', 'INVERSE', 'CASH')


def verify_t0_from_minutes(minutes, decisions):
    """Rebuild full 4h bars and recursive EMA/ATR without pandas features.

    Shares validated minute inputs, not the resampler or indicator implementation.
    Uses Decimal arithmetic; compares every eligible direction and delayed clock.
    """
    times = minutes.index.asi8
    groups = times//(240*60*10**9)
    boundaries = np.r_[0, np.flatnonzero(np.diff(groups))+1, len(minutes)]
    highs, lows, closes = (minutes[k].to_numpy() for k in ('h', 'l', 'c'))
    ema20 = ema80 = atr = previous = None
    history, rebuilt = [], {}
    for left, right in zip(boundaries[:-1], boundaries[1:]):
        if right-left != 240: continue
        close, high, low = (Decimal(str(v)) for v in (closes[right-1], highs[left:right].max(), lows[left:right].min()))
        tr = high-low if previous is None else max(high-low, abs(high-previous), abs(low-previous))
        ema20 = close if ema20 is None else (Decimal(19)*ema20+2*close)/21
        ema80 = close if ema80 is None else (Decimal(79)*ema80+2*close)/81
        atr = tr if atr is None else (13*atr+tr)/14
        history.append(close)
        # Baseline also requires finite 20-bar efficiency ratio and c.shift(20).
        ready = len(history) >= 80 and sum(abs(b-a) for a, b in zip(history[-21:-1], history[-20:])) > 0
        position = int(right)+1  # Completed 4h bar availability plus 1 minute.
        if ready and position < len(minutes) and atr > 0:
            rebuilt[position] = (1 if ema20 > ema80 else -1 if ema20 < ema80 else 0, float(close), float(atr))
        previous = close
    if set(rebuilt) != set(decisions):
        raise ValueError('independent T0 decision timestamps differ')
    for i, row in rebuilt.items():
        actual = decisions[i]
        if row[0] != actual[0] or any(abs(a-b) > 1e-6 for a, b in zip(row[1:], actual[1:])):
            raise ValueError('independent T0 direction/close/ATR differs at '+str(i))
    return dict(status='PASS', decisions=len(rebuilt), implementation='DIRECT_240_MINUTE_BLOCKS_DECIMAL_RECURSION',
                shared_input='VALIDATED_MINUTE_OHLC', independently_loaded_raw_archives=False)


def controls(decisions):
    """Keep the decision clock, previous close and ATR; change only direction.

    LONG/SHORT are constant desired directions under the original stop, sizing,
    hold limit and circuit breakers. They are not buy-and-hold or matched trades.
    """
    result = {name: {} for name in MODELS}
    for index, (side, close, atr) in decisions.items():
        if type(index) is not int or index < 0 or type(side) is not int or side not in (-1, 0, 1):
            raise ValueError('invalid decision index or direction')
        if not all(math.isfinite(v) and v > 0 for v in (close, atr)):
            raise ValueError('positive finite close and ATR required')
        for name, direction in zip(MODELS, (side, 1, -1, -side, 0)):
            result[name][index] = (direction, close, atr)
    return result


def daily_returns(rows, initial):
    if not rows or not math.isfinite(initial) or initial <= 0:
        raise ValueError('nonempty calendar and positive initial balance required')
    previous, previous_day = initial, date.fromisoformat(rows[0]['day'])-timedelta(days=1)
    values = []
    for row in rows:
        day, equity = date.fromisoformat(row['day']), row['equity']
        if day != previous_day+timedelta(days=1) or not math.isfinite(equity) or equity <= 0:
            raise ValueError('continuous calendar and finite positive equity required')
        values.append(equity/previous-1)
        previous, previous_day = equity, day
    return np.array(values)


def paired_interval(left, right, *, initial=1000, block_days=28, repetitions=2000, seed=18092026):
    """Exploratory paired circular blocks, including every halted/cash day.

    Account policies differ in position size and halt paths; this is not a
    signal-only causal effect, independent confirmation, or selection correction.
    """
    if [r['day'] for r in left] != [r['day'] for r in right]:
        raise ValueError('paired calendars differ')
    for value in (block_days, repetitions, seed):
        if type(value) is not int or value < 1: raise ValueError('positive integer settings required')
    delta = daily_returns(left, initial)-daily_returns(right, initial)
    n = len(delta)
    starts = np.random.default_rng(seed).integers(0, n, (repetitions, math.ceil(n/block_days)))
    indices = ((starts[:, :, None]+np.arange(block_days)) % n).reshape(repetitions, -1)[:, :n]
    means = delta[indices].mean(axis=1)*10000
    # A scalar sum across blocks independently checks the vectorized resampler.
    check = []
    for row in starts:
        total, remaining = 0.0, n
        for start in row:
            width = min(block_days, remaining)
            total += sum(float(delta[(int(start)+j) % n]) for j in range(width))
            remaining -= width
        check.append(total/n*10000)
    if not np.allclose(means, check, atol=1e-10, rtol=0):
        raise ValueError('scalar bootstrap verification differs')
    lo, hi = map(float, np.quantile(means, [.025, .975]))
    return dict(mean_daily_difference_bps=float(delta.mean()*10000), interval95_bps=[lo, hi],
        includes_zero=lo <= 0 <= hi, calendar_days=n, block_days=block_days,
        repetitions=repetitions, seed=seed, scalar_resampling_verified=True,
        classification='EXPLORATORY_REUSED_DATA_UNADJUSTED_FOR_MODEL_SELECTION')


def trade_sides(trades):
    rows = {}
    for side, name in ((1, 'long'), (-1, 'short')):
        selected = [t for t in trades if t['side'] == side]
        rows[name] = dict(cycles=len(selected), net_pnl=sum(t['net_pnl'] for t in selected),
            held_minutes=sum(t['exit_minute']-t['entry_minute'] for t in selected))
    if sum(r['cycles'] for r in rows.values()) != len(trades):
        raise ValueError('unknown trade side')
    return rows
