"""E006 fixed-trade attribution; counterfactuals are not portfolio backtests."""
from collections import defaultdict
import math
import numpy as np
import pandas as pd
from ..baseline.account import Costs


def cycles_from_events(events, trades):
    cycles=[]
    current=None
    for event in events:
        if event['kind']=='entry':
            if current is not None:
                raise ValueError('overlapping entries')
            current=dict(entry=event,funding=[])
        elif event['kind']=='funding':
            if current is None:
                raise ValueError('funding while flat')
            current['funding'].append(event)
        elif event['kind']=='exit':
            if current is None:
                raise ValueError('exit while flat')
            current['exit']=event
            cycles.append(current)
            current=None
        else:
            raise ValueError('unknown event')
    if current is not None or len(cycles)!=len(trades):
        raise ValueError('incomplete trade association')
    for cycle,trade in zip(cycles,trades):
        entry,exit=cycle['entry'],cycle['exit']
        if entry['time']!=trade['entry_time'] or exit['time']!=trade['exit_time'] or entry['side']!=trade['side']:
            raise ValueError('trade identity mismatch')
        if not math.isclose(entry['qty'],exit['qty'],abs_tol=1e-12) or not math.isclose(entry['qty'],trade['quantity'],abs_tol=1e-12):
            raise ValueError('trade quantity mismatch')
        gross=entry['side']*entry['qty']*(exit['price']-entry['price'])
        fees=entry['fee']+exit['fee']
        funding=sum(e['amount'] for e in cycle['funding'])
        net=gross-fees-funding
        if not math.isclose(net,trade['net_pnl'],rel_tol=0,abs_tol=1e-7):
            raise ValueError('trade attribution mismatch')
        cycle.update(trade=trade,gross=gross,fees=fees,funding_paid=funding,net=net)
    return cycles


def group_summary(rows, field):
    groups=defaultdict(list)
    for row in rows: groups[str(row[field])].append(row)
    return {key:dict(cycles=len(values),net=sum(r['net'] for r in values),gross=sum(r['gross'] for r in values),
                     fees=sum(r['fees'] for r in values),funding=sum(r['funding_paid'] for r in values))
            for key,values in sorted(groups.items())}


def describe_cycle(cycle, minutes, regimes):
    trade=cycle['trade']
    i,j=trade['entry_minute'],trade['exit_minute']
    if i<1 or j<i or minutes.index[i]!=pd.Timestamp(trade['entry_time']) or minutes.index[j]!=pd.Timestamp(trade['exit_time']):
        raise ValueError('trade index mismatch')
    side,qty=trade['side'],trade['quantity']
    pnl=side*qty*(minutes.c.iloc[i:j].to_numpy()-trade['entry_price'])
    best=max(0.,float(pnl.max())) if len(pnl) else 0.
    worst=min(0.,float(pnl.min())) if len(pnl) else 0.
    held=j-i
    bucket=('<1h' if held<60 else '1-6h' if held<360 else '6-24h' if held<1440 else '1-3d' if held<4320 else '3d+')
    return dict(entry_time=trade['entry_time'],exit_time=trade['exit_time'],net=cycle['net'],gross=cycle['gross'],
                fees=cycle['fees'],funding_paid=cycle['funding_paid'],reason=trade['reason'],side='long' if side>0 else 'short',
                holding_minutes=held,holding_bucket=bucket,entry_regime=int(regimes[i-1]),
                close_mfe=best,close_mae=worst,positive_close_then_net_loss=best>0 and cycle['net']<0,
                gross_positive_net_negative=cycle['gross']>0 and cycle['net']<0)


def early_exit(cycle, minutes, costs: Costs, cap_minutes: int):
    if type(cap_minutes) is not int or cap_minutes<=0:
        raise ValueError('positive integer time cap required')
    trade=cycle['trade'];entry=cycle['entry']
    cap=trade['entry_minute']+cap_minutes
    if cap>=trade['exit_minute']:
        return dict(changed=False,net=cycle['net'],delta=0.,exit_time=trade['exit_time'])
    time=minutes.index[cap]
    price=costs.fill(float(minutes.o.iloc[cap]),-entry['side'])
    qty=entry['qty']
    gross=entry['side']*qty*(price-entry['price'])
    # Settlement at this open is before the cap order, exactly as in E005.
    funding=sum(e['amount'] for e in cycle['funding'] if pd.Timestamp(e['time'])<=time)
    net=gross-entry['fee']-qty*price*costs.fee_bps/10000-funding
    return dict(changed=True,net=net,delta=net-cycle['net'],exit_time=time.isoformat())


def block_total_interval(rows,start,end,block_days=28,repetitions=2000,seed=17092026):
    """Circular calendar blocks, sum rather than account-return CI."""
    dates=pd.date_range(start,pd.Timestamp(end)-pd.Timedelta(days=1),freq='D')
    daily=pd.Series(0.,index=dates)
    for row in rows:
        day=pd.Timestamp(row['entry_time']).normalize()
        if day not in daily.index: raise ValueError('entry outside evaluation')
        daily.loc[day]+=row['delta']
    values=daily.to_numpy();n=len(values)
    if not n or block_days<1 or repetitions<2: raise ValueError('invalid bootstrap shape')
    rng=np.random.default_rng(seed)
    starts=rng.integers(0,n,size=(repetitions,math.ceil(n/block_days)))
    indices=((starts[:,:,None]+np.arange(block_days))%n).reshape(repetitions,-1)[:,:n]
    totals=values[indices].sum(axis=1)
    return dict(total=float(values.sum()),interval95=list(map(float,np.quantile(totals,[.025,.975]))),
                days=n,block_days=block_days,repetitions=repetitions)
