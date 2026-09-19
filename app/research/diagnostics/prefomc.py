"""Fixed announced-calendar hypothesis; no price-dependent event selection."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

DATES = ('2024-09-18','2024-11-07','2024-12-18','2025-01-29','2025-03-19',
         '2025-05-07','2025-06-18','2025-07-30','2025-09-17','2025-10-29',
         '2025-12-10','2026-01-28','2026-03-18','2026-04-29','2026-06-17','2026-07-29')


def calendar():
    rows=[]
    for date in DATES:
        release=datetime.fromisoformat(date+'T14:00:00').replace(tzinfo=ZoneInfo('America/New_York'))
        for model,days in [('FOMC',0),('PRIOR_WEEK',7)]:
            clock=release-timedelta(days=days)
            entry=clock-timedelta(days=1)+timedelta(minutes=1)
            end=clock-timedelta(minutes=1)
            utc=lambda x:pd.Timestamp(x).tz_convert('UTC').isoformat()
            rows.append(dict(model=model,meeting=date,known_on='2023-06-23' if date[:4]=='2024' else '2024-08-09',
                release_time=utc(release),entry_time=utc(entry),exit_time=utc(end),side=1))
    return rows


def attach_inputs(minutes,features,rows):
    output=[]
    for r in rows:
        entry,exit_time=(pd.Timestamp(r[k]) for k in ('entry_time','exit_time'))
        boundary=entry-pd.Timedelta(minutes=1)
        feature_time=features.index.asof(boundary)
        i,j=(int(minutes.index.get_indexer([v])[0]) for v in (entry,exit_time))
        if min(i,j)<0 or j-i!=1438 or pd.isna(feature_time):raise ValueError('missing price/feature/calendar')
        close=float(minutes.c.iloc[i-2]);atr=float(features.at[feature_time,'atr'])
        if not np.isfinite([close,atr]).all() or min(close,atr)<=0:raise ValueError('invalid lagged features')
        output.append(dict(r,entry_minute=i,exit_minute=j,decision_close=close,atr=atr,
            boundary=boundary.isoformat(),feature_time=feature_time.isoformat()))
    return output


def stats(candidate,control):
    if len(candidate)!=16 or len(control)!=16:raise ValueError('incomplete fixed calendar')
    a=np.array([r['net_bps'] for r in candidate]);b=np.array([r['net_bps'] for r in control])
    rng=np.random.default_rng(19092026);draws=[]
    for _ in range(2000):
        starts=rng.integers(0,16,size=4);idx=((starts[:,None]+np.arange(4))%16).ravel()
        draws.append([a[idx].mean(),(a-b)[idx].mean()])
    return dict(events=16,mean_net_bps=float(a.mean()),control_mean_net_bps=float(b.mean()),
        paired_excess_bps=float((a-b).mean()),mean_gross_bps=float(np.mean([r['gross_bps'] for r in candidate])),
        mean_cost_bps=float(np.mean([r['gross_bps']-r['net_bps'] for r in candidate])),
        exploratory_interval_bps=np.quantile(draws,[.025,.975],axis=0).T.tolist(),
        positive_events=int((a>0).sum()),by_year={y:dict(events=sum(r['entry_time'][:4]==y for r in candidate),
            mean_net_bps=float(np.mean([r['net_bps'] for r in candidate if r['entry_time'][:4]==y])))
            for y in sorted({r['entry_time'][:4] for r in candidate})})
