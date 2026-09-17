"""Completed-hour features to immutable order-contract snapshots."""
from decimal import Decimal as D
import json
from pathlib import Path
import numpy as np
from ..comparison.policies import family_sides
from ..execution.order_rules import Rules,Reentry,TargetAnchor,TakeProfit,StopBasis,Levels,SignalState,update_signal


def load_profiles(path: Path):
    spec=json.loads(path.read_text())
    if spec['schema_version']!=1: raise ValueError('unknown profile version')
    common=dict(spec['common'])
    for key in ('tick','atr_multiple'): common[key]=D(common[key])
    kinds=dict(reentry=Reentry,target_anchor=TargetAnchor,take_profit=TakeProfit,stop_basis=StopBasis)
    profiles={}
    for name,change in [('control',{})]+list(spec['single_axis_changes'].items()):
        values=dict(spec['control'],**change)
        if set(values)!=set(kinds) or (name!='control' and (len(change)!=1 or sum(values[k]!=spec['control'][k] for k in kinds)!=1)):
            raise ValueError('not a single-axis profile')
        profiles[name]=Rules(**common,**{k:enum(values[k]) for k,enum in kinds.items()})
    return profiles


def observations(minutes, hourly, model):
    """Original desired-direction policy retained as common signal exit control.

    Additional frozen targets may exit earlier. We do not claim isolated target
    effects independent of that shared desired-direction policy.
    """
    if model not in ('R0','F0'): raise ValueError('unsupported target-bearing model')
    sides=family_sides(hourly,model)
    positions=minutes.index.get_indexer(hourly.index)+1
    state=SignalState('E007/BTCUSDC/'+model)
    result={}
    for i,side,row in zip(positions,sides,hourly.itertuples()):
        low,high=(row.low24,row.high24) if model=='R0' else (row.low12,row.high12)
        target=row.mean if model=='R0' else (row.high12+row.low12)/2
        numbers=(row.c,row.atr,low,high,target)
        if not 0<i<len(minutes) or not all(np.isfinite(x) and x>0 for x in numbers) or low>=high:
            continue
        values=Levels(int(row.Index.value//1_000_000),*(D(str(x)) for x in numbers))
        state=update_signal(state,int(side),values)
        result[int(i)]=state
    return result
