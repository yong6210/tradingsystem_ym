"""Marginal added-inventory arithmetic; not pooled realized PnL or a signal."""
from .models import positive


def round_trip(costs, *, side, quantity, entry_mark, exit_mark):
    if type(side) is not int or side not in (-1,1):raise ValueError('explicit direction required')
    qty=positive(quantity)
    if qty%costs.step:raise ValueError('quantity not step aligned')
    entry=costs.execution(entry_mark,side);exit=costs.execution(exit_mark,-side)
    gross=side*qty*(exit-entry);fees=qty*(entry+exit)*costs.fee
    return dict(entry_fill=entry,exit_fill=exit,gross=gross,fees=fees,net=gross-fees,
                favorable_mark_move=side*(positive(exit_mark)-positive(entry_mark)),
                interpretation='marginal round trip, not campaign recovery or pooled realized PnL')
