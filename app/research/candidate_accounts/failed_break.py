"""E013 original S07 two-close return events, fixed one-hour account probe."""
from ..diagnostics.candidate_screen import candidate_conditions


def build_failed_break(minutes, bank):
    """Same event clock for fade/continuation; absent event is no command.

    Original S07 uses the previous completed hour's already-known 24h channel.
    Execution is one minute after the recovery hour closes. No midpoint target
    or extra reentry rule is added to this entry-direction diagnostic.
    """
    conditions = candidate_conditions(bank, 'S07')
    positions = minutes.index.get_indexer(conditions.index) + 1
    policies = {'S07_FADE': {}, 'S07_CONTINUE': {}}
    events = []
    hourly = bank[60]
    for k, (pos, row) in enumerate(zip(positions, conditions.itertuples())):
        if not 0 < pos < len(minutes) or not row.event:
            continue
        command = (int(row.side), float(row.close), float(row.atr))
        policies['S07_FADE'][int(pos)] = command
        policies['S07_CONTINUE'][int(pos)] = (-command[0], command[1], command[2])
        events.append(dict(completed_at=conditions.index[k].isoformat(),
                           entry_at=minutes.index[pos].isoformat(), side=command[0],
                           previous_close=float(hourly.c.iloc[k - 1]), close=command[1], atr=command[2],
                           frozen_upper=float(hourly.high24.iloc[k - 1]),
                           frozen_lower=float(hourly.low24.iloc[k - 1])))
    return policies, events
