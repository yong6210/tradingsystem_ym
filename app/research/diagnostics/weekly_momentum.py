"""One-week calendar momentum with explicit flat weekly boundaries."""
from decimal import Decimal as D
import numpy as np
import pandas as pd
from app.research.multistrategy_audit import frame_features
from app.research.diagnostics.session_reversal import event_returns as fixed_window_returns


def sessions(minutes,start,end):
    start,end=pd.Timestamp(start),pd.Timestamp(end)
    features=frame_features(minutes,240);rows=[]
    for b in pd.date_range(start.normalize(),end.normalize(),freq='W-MON'):
        entry=b+pd.Timedelta(minutes=1);exit_time=b+pd.Timedelta(days=7)
        if entry<start or exit_time>=end:continue
        old=b-pd.Timedelta(days=7,minutes=1);latest=b-pd.Timedelta(minutes=1)
        p0,p1=(float(minutes.at[t,'c']) for t in (old,latest))
        atr=float(features.at[b,'atr'])
        if not np.isfinite([p0,p1,atr]).all() or min(p0,p1,atr)<=0:raise ValueError('invalid weekly inputs')
        i,j=(int(minutes.index.get_indexer([t])[0]) for t in (entry,exit_time))
        if min(i,j)<0:raise ValueError('missing weekly boundary')
        rows.append(dict(boundary=b.isoformat(),entry_time=entry.isoformat(),exit_time=exit_time.isoformat(),
                         lag_start_close_time=old.isoformat(),lag_end_close_time=latest.isoformat(),
                         lag_start_close=p0,lag_end_close=p1,lag_return=p1/p0-1,side=int(np.sign(p1-p0)),
                         entry_minute=i,exit_minute=j,decision_close=p1,atr=atr))
    return rows


def decisions(rows,model):
    if model not in ('MOMENTUM','LONG'):raise ValueError('unregistered model')
    result={}
    for row in rows:
        result[row['entry_minute']]=(row['side'] if model=='MOMENTUM' else 1,row['decision_close'],row['atr'])
        result[row['exit_minute']]=(0,row['decision_close'],row['atr'])
    return result


def verify_signals(minutes,rows):
    # Rebuild ATR from disjoint minute blocks, without the feature generator.
    previous=None;atr=None;atr_by_index={}
    epoch=minutes.index.asi8//60_000_000_000
    _,starts,counts=np.unique(epoch//240,return_index=True,return_counts=True)
    complete=0
    h,l,c=(minutes[k].to_numpy() for k in ('h','l','c'))
    for begin,count in zip(starts,counts):
        if count!=240:continue
        stop=int(begin+count)
        assert np.all(np.diff(epoch[begin:stop])==1)
        complete+=1
        hi,lo,close=(D(str(v)) for v in (h[begin:stop].max(),l[begin:stop].min(),c[stop-1]))
        tr=hi-lo if previous is None else max(hi-lo,abs(hi-previous),abs(lo-previous))
        atr=tr if atr is None else (13*atr+tr)/14
        if complete>=14:atr_by_index[int(epoch[stop-1])+2]=atr
        previous=close
    for row in rows:
        i,j=row['entry_minute'],row['exit_minute'];t=minutes.index[i]
        assert t.dayofweek==0 and t.hour==0 and t.minute==1
        assert j-i==10079
        a,b=(D(str(c[k])) for k in (i-10082,i-2))
        side=1 if b>a else -1 if b<a else 0
        assert side==row['side']
        assert minutes.index[i-10082].isoformat()==row['lag_start_close_time']
        assert minutes.index[i-2].isoformat()==row['lag_end_close_time']
        assert float(b)==row['decision_close']
        assert abs(float(atr_by_index[int(epoch[i])])-row['atr'])<1e-6
    return dict(status='PASS',weeks=len(rows),atr='DIRECT_240_MINUTE_BLOCKS_DECIMAL_WILDER_RECURSION')


def event_returns(minutes,rows,funding,costs,model):
    # The reused helper's REVERSAL label merely selects row.side; it does not
    # invert it. Weekly directions are constructed above before this call.
    return fixed_window_returns(minutes,rows,funding,costs,'REVERSAL' if model=='MOMENTUM' else 'LONG')


def bootstrap(values):
    values=np.asarray(values,dtype=float);n=len(values);rng=np.random.default_rng(19092026);means=[]
    for _ in range(2000):
        starts=rng.integers(0,n,size=(n+3)//4)
        indices=((starts[:,None]+np.arange(4))%n).ravel()[:n]
        means.append(values[indices].mean())
    return dict(mean_bps=float(values.mean()),exploratory_interval_bps=np.quantile(means,[.025,.975]).tolist(),block_weeks=4)


def event_summary(rows):
    f=pd.DataFrame(rows)
    return dict(weeks=len(rows),**{f'mean_{k}':float(f[k].mean()) for k in ['gross_bps','net_bps','fee_bps','execution_bps','funding_bps']},
                uncertainty=bootstrap(f.net_bps),
                by_year={str(y):dict(weeks=len(g),mean_net_bps=float(g.net_bps.mean())) for y,g in f.groupby(f.entry_time.str[:4])})
