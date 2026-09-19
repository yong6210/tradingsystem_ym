"""E053 actual taker-volume extensions, not order-book queue simulation."""
import io,json
from zipfile import ZipFile
import numpy as np
import pandas as pd
from app.research.data.btcusdc import checked_bytes
from app.research.diagnostics.inventory_lab import build_features

def load_flow(root,data,index):
    manifest=json.loads((data/'manifest.json').read_text());parts=[]
    for rec in manifest['archives']:
        if rec['kind']!='klines':continue
        raw=checked_bytes(root,rec)
        with ZipFile(io.BytesIO(raw)) as z:
            with z.open(z.namelist()[0]) as fp:d=pd.read_csv(fp,usecols=['open_time','volume','taker_buy_volume'])
        d.index=pd.to_datetime(d.pop('open_time'),unit='ms',utc=True);parts.append(d)
    result=pd.concat(parts).sort_index()
    if not result.index.equals(index) or not np.isfinite(result.to_numpy()).all():raise ValueError('flow coverage')
    if ((result.taker_buy_volume<0)|(result.taker_buy_volume>result.volume+1e-8)).any():raise ValueError('invalid taker share')
    return result

def build_flow_features(m,flow):
    if not m.index.equals(flow.index) or not np.allclose(m.v,flow.volume,rtol=0,atol=1e-8):raise ValueError('flow/trade volume mismatch')
    f=build_features(m)
    b=m.resample('3min',label='right',closed='left').agg({'o':'first','h':'max','l':'min','c':'last','v':'sum'})
    buy=flow.taker_buy_volume.resample('3min',label='right',closed='left').sum()
    pressure=(2*buy-b.v)/b.v.replace(0,np.nan);busy=b.v>1.5*b.v.rolling(20).mean()
    high=b.h.shift().rolling(20).max();low=b.l.shift().rolling(20).min()
    continuation=pd.Series(np.where(busy&(pressure>.15)&(b.c>b.o),1,np.where(busy&(pressure<-.15)&(b.c<b.o),-1,0)),index=b.index)
    absorption=pd.Series(np.where(busy&(pressure<-.15)&(b.l<low)&(b.c>low)&(b.c>b.o),1,np.where(busy&(pressure>.15)&(b.h>high)&(b.c<high)&(b.c<b.o),-1,0)),index=b.index)
    for name,s in [('flow_continuation',continuation),('flow_absorption',absorption)]:
        s.index=s.index+pd.Timedelta(minutes=1);f[name]=s.reindex(m.index,method='ffill')
    for n in (3,15,60):f['flow'+str(n)]=((2*flow.taker_buy_volume-flow.volume).rolling(n).sum()/flow.volume.rolling(n).sum().replace(0,np.nan)).shift(2)
    return f

def fit_flow_ridge(m,f,start,end):
    columns=['r3','r15','r60','direction','er','z','vol_ratio','flow3','flow15','flow60']
    X=f[columns].to_numpy(float);y=(m.o.shift(-60)/m.o-1).to_numpy(float);times=m.index;dec=f.decision.to_numpy().astype(bool);logs=[]
    for left in pd.date_range(start,end,freq='MS',inclusive='left'):
        right=left+pd.offsets.MonthBegin(1);train=(times>=left-pd.Timedelta(days=90))&(times<left-pd.Timedelta(days=1,minutes=60))&dec
        train &=np.isfinite(X).all(axis=1)&np.isfinite(y);test=(times>=left)&(times<right)&np.isfinite(X).all(axis=1)
        a=X[train];target=y[train]
        if len(a)<1000:raise ValueError('insufficient mature training')
        mean=a.mean(axis=0);scale=np.maximum(a.std(axis=0),1e-9);a=np.c_[np.ones(len(a)),np.clip((a-mean)/scale,-8,8)]
        penalty=np.eye(a.shape[1])*.01;penalty[0,0]=0
        coef=np.linalg.solve(a.T@a/len(a)+penalty,a.T@target/len(a));pred=np.c_[np.ones(int(test.sum())),np.clip((X[test]-mean)/scale,-8,8)]@coef
        f.loc[test,'ridge_forecast']=pred;f.loc[test,'ridge']=np.where(pred>.0015,1,np.where(pred<-.0015,-1,0))
        logs.append({'month':left.isoformat(),'training_rows':len(a),'last_label_maturity':(times[train][-1]+pd.Timedelta(minutes=60)).isoformat(),'coef':coef.tolist(),'mean':mean.tolist(),'scale':scale.tolist()})
    return logs

def model_features(f,family):
    result=f.copy(deep=False)
    if family=='flow_continuation':result['retest']=result['flow_continuation'];engine='retest'
    elif family=='flow_absorption':result['sweep']=result['flow_absorption'];engine='sweep'
    elif family=='flow_ridge':engine='ridge'
    else:raise ValueError(family)
    return result,engine
