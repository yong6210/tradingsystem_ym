"""Six fixed policies; no optimizer. Decisions follow completed candles by 1 min."""
import numpy as np
from ..baseline.engine import policies as trend_policies


def family_sides(frame, family):
    """Desired exposure state; execution/risk stops remain in the common engine.

    Following a stop, a still-active desired state may re-enter at a later hourly
    decision. This is deliberate and distinct from silently forbidding re-entry.
    """
    state = 0
    target = None
    sides = []
    for row in frame.itertuples():
        valid = all(np.isfinite(x) for x in (row.atr,row.er,row.z,row.high24,row.low24,row.high12,row.low12))
        if not valid:
            sides.append(0)
            continue
        if family == 'B0':
            if state == 1 and row.c < row.low12: state = 0
            if state == -1 and row.c > row.high12: state = 0
            if row.c > row.high24: state = 1
            elif row.c < row.low24: state = -1
        elif family == 'R0':
            if (state == 1 and row.z >= 0) or (state == -1 and row.z <= 0) or row.er >= .3:
                state = 0
            if not state and row.er < .2:
                if row.z <= -2: state = 1
                elif row.z >= 2: state = -1
        elif family == 'F0':
            if state and (state*(row.c-target) >= 0 or row.er >= .3):
                state, target = 0, None
            if not state and row.er < .2:
                long = row.l < row.low12 and row.c > row.low12
                short = row.h > row.high12 and row.c < row.high12
                if long != short:
                    proposed = 1 if long else -1
                    mid = (row.high12+row.low12)/2
                    if proposed*(mid-row.c) > 0:
                        state, target = proposed, mid
        else:
            raise ValueError('unknown family')
        sides.append(state)
    return sides


def comparison_policies(minutes, bank):
    result = trend_policies(minutes, bank)
    frame = bank[60]
    positions = minutes.index.get_indexer(frame.index)+1
    for model in ('B0','R0','F0'):
        sides = family_sides(frame,model)
        result[model] = {int(i):(int(side),float(close),float(atr))
                         for i,side,close,atr in zip(positions,sides,frame.c,frame.atr)
                         if 0 < i < len(minutes) and np.isfinite(atr) and atr > 0}
    return result
