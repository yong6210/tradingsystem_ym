"""E009: one frozen direction-aligned taker filter on S02 events."""
import numpy as np

from .policies import entry_conditions

MODELS = ('S02', 'S06A')


def flow_conditions(bank, hourly, model):
    if model not in MODELS:
        raise ValueError('unsupported flow model')
    base = entry_conditions(bank, 'S02')
    if not hourly.index.equals(base.index):
        raise ValueError('flow/price completed-hour mismatch')
    base['buy_share'] = hourly.buy_share
    # 50% is the neutral boundary, not an outcome-selected threshold.
    base['flow_aligned'] = (base.side * (2 * base.buy_share - 1) > 0) & np.isfinite(base.buy_share)
    if model == 'S06A':
        base['event'] &= base.flow_aligned
    return base


def build_flow_policy(minutes, bank, hourly, model):
    conditions = flow_conditions(bank, hourly, model)
    frame = bank[60]
    positions = minutes.index.get_indexer(frame.index) + 1
    desired, decisions = 0, {}
    for k, (pos, row) in enumerate(zip(positions, frame.itertuples())):
        if not 0 < pos < len(minutes) or not bool(conditions.valid.iloc[k]):
            continue
        exiting = ((desired == 1 and row.c < row.low12) or
                   (desired == -1 and row.c > row.high12))
        if exiting:
            desired = 0
            decisions[int(pos)] = (0, float(row.c), float(row.atr))
        elif bool(conditions.event.iloc[k]):
            desired = int(conditions.side.iloc[k])
            decisions[int(pos)] = (desired, float(row.c), float(row.atr))
    return decisions
