"""Sparse fresh-entry events plus explicit family exits; no parameter search."""
import numpy as np
from ..diagnostics.candidate_screen import candidate_conditions

MODELS=('S04','S05','S02','S08')


def entry_conditions(bank, model):
    if model not in MODELS: raise ValueError('unsupported candidate')
    data=candidate_conditions(bank,model).copy()
    if model=='S08':
        base=candidate_conditions(bank,'S02')
        # A literal filter on the SAME breakout event clock, not additional
        # events caused solely by a squeeze condition switching on/off.
        data['event']=base.event & (base.side==data.side) & data.valid
    if model in ('S04','S05'):
        # Recovery can overshoot the mean; do not chase a completed target.
        f=bank[15]
        data['event'] &= data.side*(f['mean']-f.c)>0
    return data


def build_policy(minutes,bank,model):
    conditions=entry_conditions(bank,model)
    period=15 if model in ('S04','S05') else 60
    frame=bank[period]
    higher=bank[240].reindex(frame.index,method='ffill')
    positions=minutes.index.get_indexer(frame.index)+1
    desired=0;decisions={};counts=dict(entry_events=0,exit_signals=0,same_direction_fresh_events=0)
    for k,(pos,row) in enumerate(zip(positions,frame.itertuples())):
        if not 0<pos<len(minutes) or not bool(conditions.valid.iloc[k]): continue
        exiting=False
        if model in ('S04','S05'):
            exiting=bool(desired and (desired*row.z>=0 or higher.er.iloc[k]>=.25))
        else:
            exiting=bool((desired==1 and row.c<row.low12) or (desired==-1 and row.c>row.high12))
        # Explicit exit wins a conflicting new signal at this observation.
        if exiting:
            desired=0;decisions[int(pos)]=(0,float(row.c),float(row.atr));counts['exit_signals']+=1
        elif bool(conditions.event.iloc[k]):
            side=int(conditions.side.iloc[k])
            counts['same_direction_fresh_events']+=int(side==desired)
            desired=side
            decisions[int(pos)]=(side,float(row.c),float(row.atr));counts['entry_events']+=1
        # No event is no command, NOT a neutral target-position command.
    return decisions,counts
