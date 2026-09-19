"""E047 delayed archived OI, with explicit missing-input abstention."""
from decimal import Decimal as D
import io
from zipfile import ZipFile
import numpy as np
import pandas as pd


def parse_day(path,date):
    with ZipFile(path) as z:
        members=z.infolist()
        if len(members)!=1 or members[0].file_size>4*1024*1024:raise ValueError('ZIP scope/size')
        frame=pd.read_csv(io.BytesIO(z.read(members[0])),dtype=str)
    needed={'create_time','symbol','sum_open_interest'}
    if not needed.issubset(frame):raise ValueError('OI schema')
    stamps=pd.to_datetime(frame.create_time,utc=True,errors='coerce')
    values=pd.to_numeric(frame.sum_open_interest,errors='coerce')
    day=pd.Timestamp(date,tz='UTC');expected=pd.date_range(day,periods=288,freq='5min')
    invalid=(stamps.isna() | ~np.isfinite(values) | (values<=0) | (frame.symbol!='BTCUSDT') |
        (stamps<day) | (stamps>=day+pd.Timedelta(days=1)) | ~stamps.isin(expected))
    duplicates=int(stamps.duplicated().sum());missing=int(len(expected.difference(stamps.dropna())))
    endpoint=day+pd.Timedelta(hours=23,minutes=55)
    valid=not invalid.any() and duplicates==0 and (stamps==endpoint).sum()==1
    record=dict(date=date,rows=len(frame),duplicate_times=duplicates,invalid_rows=int(invalid.sum()),
        missing_slots=missing,input_monotonic=bool(stamps.is_monotonic_increasing),endpoint_usable=bool(valid))
    ordered=frame.assign(stamp=stamps).sort_values('stamp')
    value=ordered.loc[ordered.stamp==endpoint,'sum_open_interest'].iloc[0] if valid else None
    return value,record


def signals(minutes,oi,start,end):
    start,end=pd.Timestamp(start),pd.Timestamp(end);rows=[]
    for b in pd.date_range(start,end,freq='D',inclusive='left'):
        entry=b+pd.Timedelta(minutes=1);exit_time=b+pd.Timedelta(days=1)
        if exit_time>=end:continue
        old_date=str((b-pd.Timedelta(days=3)).date());new_date=str((b-pd.Timedelta(days=2)).date())
        a,c=oi.get(old_date),oi.get(new_date);valid=a is not None and c is not None
        if valid and min(D(a),D(c))<=0:raise ValueError('nonpositive OI input')
        change=D(c)/D(a)-1 if valid else None
        previous=float(minutes.at[b-pd.Timedelta(days=1,minutes=1),'c'])
        latest=float(minutes.at[b-pd.Timedelta(minutes=1),'c'])
        if not np.isfinite([previous,latest]).all() or min(previous,latest)<=0:raise ValueError('price input')
        price_down=latest<previous
        selected=valid and price_down and change>=D('.05')
        i,j=(int(minutes.index.get_indexer([t])[0]) for t in (entry,exit_time))
        if min(i,j)<0 or j-i!=1439:raise ValueError('price event grid')
        rows.append(dict(boundary=b.isoformat(),entry_time=entry.isoformat(),exit_time=exit_time.isoformat(),
            entry_minute=i,exit_minute=j,old_oi_date=old_date,new_oi_date=new_date,old_oi=a,new_oi=c,
            oi_change=str(change) if valid else None,input_valid=valid,price_down=price_down,
            previous_close=previous,decision_close=latest,side=-1 if selected else 0,control_side=-1 if valid and price_down else 0))
    return rows


def decisions(rows):
    result={}
    for r in rows:
        if not r['side']:continue
        i,j=r['entry_minute'],r['exit_minute']
        if i in result or j in result:raise ValueError('colliding commands')
        result[i]=(r['side'],r['decision_close'],r['atr']);result[j]=(0,r['decision_close'],r['atr'])
    return result


def event_stats(candidate,control):
    a=np.array([r['net_bps'] for r in candidate]);b=np.array([r['net_bps'] for r in control]);n=len(a)
    active=np.array([bool(r['side']) for r in candidate]);base_active=np.array([bool(r['side']) for r in control])
    if n!=len(b) or n==0:raise ValueError('event calendar')
    rng=np.random.default_rng(19092026);draws=[]
    for _ in range(2000):
        starts=rng.integers(0,n,size=(n+27)//28);idx=((starts[:,None]+np.arange(28))%n).ravel()[:n]
        draws.append([a[idx].mean(),(a-b)[idx].mean()])
    return dict(days=n,active_events=int(active.sum()),control_events=int(base_active.sum()),
        active_mean_net_bps=float(a[active].mean()) if active.any() else None,
        control_active_mean_net_bps=float(b[base_active].mean()) if base_active.any() else None,
        active_mean_gross_bps=float(np.mean([r['gross_bps'] for r in candidate if r['side']])) if active.any() else None,
        calendar_mean_net_bps=float(a.mean()),control_calendar_mean_net_bps=float(b.mean()),
        calendar_excess_bps=float((a-b).mean()),exploratory_calendar_interval_bps=np.quantile(draws,[.025,.975],axis=0).T.tolist(),
        by_year={year:dict(active_events=sum(bool(r['side']) for r in candidate if r['entry_time'][:4]==year),
            mean_calendar_net_bps=float(np.mean([r['net_bps'] for r in candidate if r['entry_time'][:4]==year])))
            for year in sorted({r['entry_time'][:4] for r in candidate})})
