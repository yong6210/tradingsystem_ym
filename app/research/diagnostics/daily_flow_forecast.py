"""Fixed causal daily ridge pair: price features versus one added trade-flow feature."""
import math
import numpy as np
import pandas as pd

PRICE=['return_1d','return_7d','realized_vol_1d']
FLOW=PRICE+['imbalance_1d']


def daily_panel(minutes,flow):
    if not minutes.index.equals(flow.index) or not np.array_equal(minutes.to_numpy(),flow[minutes.columns].to_numpy()):
        raise ValueError('price/flow sources differ')
    g=minutes.resample('1D',origin='epoch')
    d=g.agg(dict(c='last',v='sum'));count=g.c.count()
    d=d.loc[count==1440].copy()
    buys=flow.taker_buy_volume.resample('1D',origin='epoch').sum().reindex(d.index)
    square=np.log(minutes.c/minutes.c.shift()).pow(2).resample('1D',origin='epoch').sum(min_count=1440).reindex(d.index)
    x=pd.DataFrame(dict(return_1d=d.c/d.c.shift()-1,return_7d=d.c/d.c.shift(7)-1,
                        realized_vol_1d=np.sqrt(square),imbalance_1d=2*buys/d.v.replace(0,np.nan)-1,
                        decision_close=d.c))
    x.index+=pd.Timedelta(days=1)
    x['entry_time']=x.index+pd.Timedelta(minutes=1)
    x['exit_time']=x.index+pd.Timedelta(days=1)
    a=minutes.o.reindex(pd.DatetimeIndex(x.entry_time)).to_numpy()
    b=minutes.o.reindex(pd.DatetimeIndex(x.exit_time)).to_numpy()
    x['target_bps']=(b/a-1)*10000
    return x


def predict(x,y,current,columns,window=180):
    start,stop=current-window-1,current-1
    if start<0:raise ValueError('insufficient training history')
    train=x.iloc[start:stop][columns].to_numpy(dtype=float)
    target=y.iloc[start:stop].to_numpy(dtype=float);latest=x.iloc[current][columns].to_numpy(dtype=float)
    if len(train)!=window or not all(np.isfinite(a).all() for a in (train,target,latest)):
        raise ValueError('nonfinite or missing training input')
    mu=train.mean(axis=0);sd=train.std(axis=0);sd=np.where(sd==0,1.,sd)
    z=(train-mu)/sd;center=target.mean();beta=np.linalg.solve(z.T@z+window*np.eye(len(columns)),z.T@(target-center))
    # Independent numerical formulation: ridge as augmented least squares.
    augmented=np.vstack([z,np.sqrt(window)*np.eye(len(columns))])
    response=np.r_[target-center,np.zeros(len(columns))]
    reference=np.linalg.lstsq(augmented,response,rcond=None)[0]
    if not np.allclose(beta,reference,rtol=0,atol=1e-8):raise ValueError('ridge formulation mismatch')
    forecast=float(center+((latest-mu)/sd)@beta)
    return dict(prediction_bps=forecast,training_start=x.index[start].isoformat(),
                training_last=x.index[stop-1].isoformat(),training_last_target_exit=x.iloc[stop-1].exit_time.isoformat(),
                train_mean=mu.tolist(),train_std=sd.tolist(),intercept_bps=float(center),coefficients=beta.tolist())


def signals(panel,funding,start,end):
    times=np.array([e['fundingTime'] for e in funding],dtype=np.int64)
    result={k:[] for k in ('PRICE','FLOW')}
    for i,b in enumerate(panel.index):
        if b<pd.Timestamp(start) or panel.iloc[i].exit_time>=pd.Timestamp(end):continue
        if b>=pd.Timestamp(end):break
        # Check consecutive training calendar and strictly matured labels.
        if i<181 or panel.index[i]-panel.index[i-181]!=pd.Timedelta(days=181):raise ValueError('training calendar gap')
        k=int(np.searchsorted(times,int(b.timestamp()*1000),side='left'))
        if k<3:raise ValueError('insufficient past funding')
        past=funding[k-3:k];rate=sum(float(e['fundingRate']) for e in past)
        if b-pd.Timestamp(past[0]['fundingTime'],unit='ms',tz='UTC')>pd.Timedelta(hours=25):raise ValueError('stale past funding')
        threshold=18+abs(rate)*10000+2*.1/float(panel.iloc[i].decision_close)*10000
        for name,cols in [('PRICE',PRICE),('FLOW',FLOW)]:
            p=predict(panel,panel.target_bps,i,cols)
            if pd.Timestamp(p['training_last_target_exit'])>=b:raise ValueError('unmatured label')
            side=int(np.sign(p['prediction_bps'])) if abs(p['prediction_bps'])>threshold else 0
            result[name].append(dict(boundary=b.isoformat(),entry_time=panel.iloc[i].entry_time.isoformat(),
                exit_time=panel.iloc[i].exit_time.isoformat(),side=side,threshold_bps=threshold,
                decision_close=float(panel.iloc[i].decision_close),past_funding_times=[e['fundingTime'] for e in past],**p))
    return result


def verify_features(minutes,flow,panel):
    checked=0
    for b,row in panel.iterrows():
        j=int(minutes.index.searchsorted(b));i=j-1440
        if i<1 or j-i!=1440:continue
        prices=minutes.c.iloc[i-1:j].to_numpy()
        vol=math.sqrt(math.fsum(math.log(float(v)/float(u))**2 for u,v in zip(prices,prices[1:])))
        volume=math.fsum(flow.v.iloc[i:j]);buy=math.fsum(flow.taker_buy_volume.iloc[i:j])
        values={'realized_vol_1d':vol,'imbalance_1d':2*buy/volume-1 if volume else math.nan}
        if i>=1:values['return_1d']=float(minutes.c.iloc[j-1]/minutes.c.iloc[i-1]-1)
        if j>7*1440:values['return_7d']=float(minutes.c.iloc[j-1]/minutes.c.iloc[j-7*1440-1]-1)
        for key,value in values.items():
            if pd.isna(row[key]):continue
            if not math.isclose(value,row[key],rel_tol=0,abs_tol=1e-10):raise ValueError('feature mismatch '+key)
        checked+=1
    return dict(status='PASS',daily_rows=checked,method='DIRECT_MINUTE_INDEX_AND_MATH_FSUM')


def interval(values):
    a=np.asarray(values,dtype=float);n=len(a);rng=np.random.default_rng(19092026);means=[]
    for _ in range(2000):
        starts=rng.integers(0,n,size=(n+27)//28)
        idx=((starts[:,None]+np.arange(28))%n).ravel()[:n];means.append(float(a[idx].mean()))
    return dict(mean_bps=float(a.mean()),interval_bps=np.quantile(means,[.025,.975]).tolist(),block_days=28)
