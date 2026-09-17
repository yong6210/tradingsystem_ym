"""E011: finite-lived pullback episodes and matched fifteen-minute controls."""
import numpy as np

from ..baseline.engine import policies

MODELS = ('T0', 'C4', 'P4', 'C15', 'P15')
MAX_WAIT_BARS = 8


def pullback_context(bank):
    f = bank[15]
    h = bank[240]
    valid_high = h.ema80.notna() & h.atr.notna() & h.er.notna() & h.c.shift(20).notna()
    higher = h.reindex(f.index, method='ffill')
    valid = valid_high.reindex(f.index, method='ffill').astype('boolean').fillna(False).astype(bool)
    valid &= np.isfinite(f[['c', 'o', 'h', 'l', 'ema20', 'atr']]).all(axis=1) & (f.atr > 0)
    direction = np.sign(higher.ema20-higher.ema80).fillna(0).astype(int)
    out = f[['o', 'h', 'l', 'c', 'ema20', 'atr']].copy()
    out['atr4'] = higher.atr
    out['valid'] = valid
    out['direction'] = direction.where(valid, 0)
    out['displacement'] = (f.c-f.ema20)/f.atr
    out['displaced_side'] = out.direction.where(out.direction*out.displacement < -.5, 0)
    return out


def episode_events(context):
    """Signal state only; pending entry signals are not exchange orders."""
    armed = None
    prior_displaced = 0
    events, audit = {}, []
    for k, row in enumerate(context.itertuples()):
        side = int(row.direction)
        displaced = int(row.displaced_side)
        if armed is not None:
            armed_k, armed_side, armed_time = armed
            age = k-armed_k
            reason = ('invalidated' if not row.valid or side != armed_side
                      else 'expired' if age > MAX_WAIT_BARS else None)
            if reason:
                audit.append(dict(kind=reason, time=row.Index.isoformat(), armed_at=armed_time.isoformat(), side=armed_side))
                armed = None
            elif age > 0:
                previous = context.iloc[k-1]
                confirms = (side*(row.c-row.o) > 0 and
                            (row.c > previous.h if side == 1 else row.c < previous.l))
                if confirms:
                    events[k] = side
                    audit.append(dict(kind='confirmed', time=row.Index.isoformat(), armed_at=armed_time.isoformat(),
                                      side=side, wait_bars=age))
                    armed = None
        # No same-bar confirmation, no extension of an existing episode, and
        # no repeated arming just because displacement remains extreme.
        if armed is None and k not in events and row.valid and displaced and displaced != prior_displaced:
            armed = (k, displaced, row.Index)
            audit.append(dict(kind='armed', time=row.Index.isoformat(), side=displaced))
        prior_displaced = displaced
    return events, audit


def build_pullback_policies(minutes, bank):
    context = pullback_context(bank)
    events, audit = episode_events(context)
    result = {m: {} for m in MODELS}
    result['T0'] = policies(minutes, bank)['T0']
    positions = minutes.index.get_indexer(context.index)+1
    previous_side = 0
    for k, (pos, row) in enumerate(zip(positions, context.itertuples())):
        if not 0 < pos < len(minutes): continue
        side = int(row.direction)
        if not row.valid:
            if previous_side:
                for m in MODELS[1:]: result[m][int(pos)] = (0, float(row.c), float(row.atr4))
            previous_side = 0
            continue
        for control, candidate, atr in (('C4', 'P4', row.atr4), ('C15', 'P15', row.atr)):
            result[control][int(pos)] = (side, float(row.c), float(atr))
            if side != previous_side:
                # Exit old exposure first. A new trend needs its own later
                # armed-and-confirmed pullback before candidate entry.
                result[candidate][int(pos)] = (0, float(row.c), float(atr))
            elif k in events:
                result[candidate][int(pos)] = (events[k], float(row.c), float(atr))
        previous_side = side
    return result, context, audit
