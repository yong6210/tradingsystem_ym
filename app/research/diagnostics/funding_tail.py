"""Predeclared lower-decile funding rebound, without outcome-selected parameters."""
from decimal import Decimal as D
import numpy as np
import pandas as pd

EIGHT=8*3600_000
WINDOW=540


def ranks(funding):
    times=np.array([e['fundingTime'] for e in funding],dtype=np.int64)
    rates=np.array([float(e['fundingRate']) for e in funding])
    if not len(times) or not np.isfinite(rates).all():raise ValueError('empty/invalid funding')
    slots=times//EIGHT*EIGHT
    if np.any(times-slots>60000) or np.any(np.diff(slots)!=EIGHT):raise ValueError('funding calendar gap/duplicate/deviation')
    rows=[]
    for i in range(WINDOW,len(times)):
        old=rates[i-WINDOW:i];value=rates[i]
        lower=int((old<value).sum());equal=int((old==value).sum())
        rows.append(dict(index=i,boundary_ms=int(slots[i]),funding_time_ms=int(times[i]),funding_rate=str(funding[i]['fundingRate']),
            history_first_ms=int(times[i-WINDOW]),history_last_ms=int(times[i-1]),history_count=WINDOW,
            lower_count=lower,equal_count=equal,midrank=(lower+equal/2)/WINDOW,tail=2*lower+equal<=WINDOW/5))
    return rows


def signals(funding,start,end):
    start,end=pd.Timestamp(start),pd.Timestamp(end);rows=[];free_at=None
    for row in ranks(funding):
        b=pd.Timestamp(row['boundary_ms'],unit='ms',tz='UTC')
        entry=b+pd.Timedelta(minutes=2);exit_time=b+pd.Timedelta(days=1,minutes=1)
        if b<start or exit_time>=end:continue
        blocked=free_at is not None and entry<=free_at
        selected=row['tail'] and not blocked
        if selected:free_at=exit_time
        rows.append(dict(**row,boundary=b.isoformat(),entry_time=entry.isoformat(),exit_time=exit_time.isoformat(),
            hour=b.hour,overlap_suppressed=bool(row['tail'] and blocked),side=int(selected)))
    return rows


def verify_ranks(funding,rows):
    selected=[];last_exit=None
    for row in rows:
        i=row['index'];now=D(str(funding[i]['fundingRate']))
        old=[D(str(e['fundingRate'])) for e in funding[i-WINDOW:i]]
        lower=sum(r<now for r in old);equal=sum(r==now for r in old)
        percentile=(D(lower)+D(equal)/2)/D(WINDOW)
        if abs(float(percentile)-row['midrank'])>1e-14:raise ValueError('independent percentile mismatch')
        if row['lower_count']!=lower or row['equal_count']!=equal or row['tail']!=(percentile<=D('.1')):raise ValueError('rank counts differ')
        entry=pd.Timestamp(row['entry_time']);exit_time=pd.Timestamp(row['exit_time'])
        expected=percentile<=D('.1') and (last_exit is None or entry>last_exit)
        if row['side']!=int(expected):raise ValueError('selection/overlap mismatch')
        if entry.value//1_000_000<=row['funding_time_ms']:raise ValueError('signal not yet published')
        if expected:last_exit=exit_time;selected.append(row['index'])
    return dict(status='PASS_DECIMAL_RANKS_AND_NONOVERLAP',rows=len(rows),selected_indices=selected)


def decision_map(rows):
    result={}
    for row in rows:
        if not row['side']:continue
        i,j=row['entry_minute'],row['exit_minute']
        if i in result or j in result:raise ValueError('colliding fixed-window commands')
        result[i]=(1,row['decision_close'],row['atr'])
        result[j]=(0,row['decision_close'],row['atr'])
    return result


def event_stats(signals,all_long,selected):
    frame=pd.DataFrame(all_long);frame['active']=[r['side'] for r in signals];frame['hour']=[r['hour'] for r in signals]
    a=frame.loc[frame.active==1]
    if len(a)==0:return dict(active_events=0,mean_net_bps=None,matched_excess_bps=None,by_year={})
    means=frame.groupby('hour').net_bps.mean()
    matched=sum(float(means[h])*int((a.hour==h).sum()) for h in means.index)/len(a)
    # Resample complete days so overlap among unconditional clock controls is retained.
    dates=pd.date_range(frame.entry_time.iloc[0][:10],frame.entry_time.iloc[-1][:10],freq='D')
    all_days=np.zeros((len(dates),3,4));positions={str(t.date()):i for i,t in enumerate(dates)}
    for r in frame.itertuples():
        i=positions[r.entry_time[:10]];h=r.hour//8
        all_days[i,h]=[r.net_bps,1,r.net_bps*r.active,r.active]
    rng=np.random.default_rng(19092026);boot=[]
    for _ in range(2000):
        starts=rng.integers(0,len(dates),size=(len(dates)+27)//28)
        idx=((starts[:,None]+np.arange(28))%len(dates)).ravel()[:len(dates)]
        total=all_days[idx].sum(axis=0);n=total[:,3].sum()
        if n:
            mean=total[:,2].sum()/n;baseline=((total[:,0]/total[:,1])*total[:,3]).sum()/n
            boot.append([mean,mean-baseline])
    if any(abs(v['net_bps']-u['net_bps'])>1e-9 for r,v,u in zip(signals,selected,all_long,strict=True) if r['side']):
        raise ValueError('selected event costs differ from matching long event')
    return dict(active_events=len(a),mean_net_bps=float(a.net_bps.mean()),mean_gross_bps=float(a.gross_bps.mean()),
        mean_fee_bps=float(a.fee_bps.mean()),mean_execution_bps=float(a.execution_bps.mean()),mean_funding_bps=float(a.funding_bps.mean()),
        mean_cost_bps=float((a.gross_bps-a.net_bps).mean()),matched_unconditional_mean_bps=float(matched),
        matched_excess_bps=float(a.net_bps.mean()-matched),calendar_day_mean_bps=float(a.net_bps.sum()/len(dates)),
        exploratory_interval_bps=np.quantile(boot,[.025,.975],axis=0).T.tolist(),bootstrap_valid=len(boot),
        by_year={str(y):dict(events=len(g),mean_net_bps=float(g.net_bps.mean())) for y,g in a.groupby(a.entry_time.str[:4])})
