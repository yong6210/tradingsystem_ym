"""Finite-window H01 risk pair; does not alter the frozen execution engine."""
from dataclasses import replace

import pandas as pd

from app.research.baseline.risk import Risk


def window_minutes(start, end):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    minute = pd.Timedelta(minutes=1)
    if (pd.isna(start) or pd.isna(end) or start.tzinfo is None or end.tzinfo is None
            or end <= start or start.value % minute.value or end.value % minute.value):
        raise ValueError('ordered timezone-aware whole-minute window required')
    return int((end-start) / minute)


def risk_pair(start, end, control=Risk()):
    """Age cannot reach the variant cap in [start,end), entered flat.

    This only disables age exits in this finite backtest. It is not an infinite
    live holding policy. All other Risk fields are preserved by dataclass copy.
    """
    count = window_minutes(start, end)
    if type(control.maximum_hold_minutes) is not int or control.maximum_hold_minutes <= 0:
        raise ValueError('positive integer control holding cap required; zero is not disabled')
    return {'control': control, 'no_time_exit': replace(
        control, maximum_hold_minutes=max(count+1, control.maximum_hold_minutes+1))}


def verify_window(index, start, end):
    """Reject gaps, duplicates and incomplete bounds; never fill missing prices."""
    count = window_minutes(start, end)
    selected = index[(index >= pd.Timestamp(start)) & (index < pd.Timestamp(end))]
    if (len(selected) != count or selected.has_duplicates or not selected.is_monotonic_increasing
            or selected[0] != pd.Timestamp(start)
            or selected[-1]+pd.Timedelta(minutes=1) != pd.Timestamp(end)
            or (selected.asi8[1:]-selected.asi8[:-1] != 60_000_000_000).any()):
        raise ValueError('complete regular minute window required')
    return count


def verify_no_time_exit(result, start, end, risk):
    count = window_minutes(start, end)
    if risk.maximum_hold_minutes <= count:
        raise ValueError('variant cap must exceed the full evaluation window')
    for trade in result['trades']:
        if (trade['reason'] == 'time_exit'
                or not 0 <= trade['exit_minute']-trade['entry_minute'] < count
                or not pd.Timestamp(start) <= pd.Timestamp(trade['entry_time'])
                <= pd.Timestamp(trade['exit_time']) < pd.Timestamp(end)):
            raise ValueError('variant trade violates finite-window contract')
    return {'status': 'PASS', 'maximum_possible_age_minutes': count-1,
            'cap_minutes': risk.maximum_hold_minutes, 'time_exits': 0}
