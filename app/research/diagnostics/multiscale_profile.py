"""Causal executed-volume profiles; prices are binned, never candle-allocated."""
from dataclasses import dataclass
import hashlib
import json
import zipfile
import numpy as np
import pandas as pd

BIN = 50.
SLOT = 900_000


def aggregate_archives(directory, start, end):
    left = int(pd.Timestamp(start).timestamp()*1000)
    right = int(pd.Timestamp(end).timestamp()*1000)
    hist = np.zeros(((right-left)//SLOT, 4000), dtype=float)
    minute_volume = np.zeros((right-left)//60_000)
    manifest = json.loads((directory/'manifest.json').read_text())
    stats=[];previous_id=None;previous_time=None
    for record in manifest['archives']:
        path=directory/record['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256']
        count=0;gaps=0;volume=0.
        with zipfile.ZipFile(path) as z, z.open(z.namelist()[0]) as fp:
            for chunk in pd.read_csv(fp, chunksize=500000):
                ids=chunk.agg_trade_id.to_numpy('int64')
                times=chunk.transact_time.to_numpy('int64')
                px=chunk.price.to_numpy(float);qty=chunk.quantity.to_numpy(float)
                assert np.isfinite(px).all() and np.isfinite(qty).all()
                assert (px>0).all() and (qty>0).all()
                assert (np.diff(ids)>0).all() and (np.diff(times)>=0).all()
                if previous_id is not None:
                    assert ids[0]>previous_id and times[0]>=previous_time
                    gaps+=int(ids[0]-previous_id-1)
                gaps+=int((np.diff(ids)-1).sum())
                previous_id=int(ids[-1]);previous_time=int(times[-1])
                assert ((times>=left)&(times<right)).all()
                slots=(times-left)//SLOT; bins=np.floor(px/BIN).astype(int)
                assert bins.max()<hist.shape[1]
                np.add.at(hist,(slots,bins),qty)
                np.add.at(minute_volume,(times-left)//60000,qty)
                count+=len(chunk);volume+=float(qty.sum())
        stats.append(dict(month=record['month'],rows=count,id_gaps=gaps,volume=volume))
    occupied=np.flatnonzero(hist.sum(axis=0)>0)
    lo,hi=int(occupied[0]),int(occupied[-1])+1
    return hist[:,lo:hi].copy(),lo,minute_volume,stats


@dataclass(frozen=True)
class Zone:
    low: float
    high: float
    poc: float
    share: float
    horizon: str


def zones_from_hist(values, offset, horizon):
    total=float(values.sum())
    if total<=0:return []
    smooth=np.convolve(values,[.25,.5,.25],mode='same')
    ranked=np.argsort(-smooth,kind='stable')
    chosen=[]
    for k in ranked:
        k=int(k)
        if smooth[k]<=0 or (k and smooth[k]<smooth[k-1]) or (k+1<len(smooth) and smooth[k]<smooth[k+1]):continue
        if any(abs(k-j)<=3 for j in chosen):continue
        chosen.append(k)
        if len(chosen)==5:break
    result=[]
    for k in chosen:
        lo=max(0,k-1);hi=min(len(values),k+2)
        result.append(Zone((lo+offset)*BIN,(hi+offset)*BIN,(k+offset+.5)*BIN,
                           float(values[lo:hi].sum()/total),horizon))
    return result


class Profiles:
    def __init__(self,hist,offset,start_ms):
        self.prefix=np.vstack([np.zeros((1,hist.shape[1])),np.cumsum(hist,axis=0)])
        self.offset=offset;self.start_ms=start_ms;self.cache={}

    def snapshot(self,t_ms,anchor_ms=None):
        # Full 15m interval plus one minute delivery delay. Never current slot.
        end=max(0,min(len(self.prefix)-1,(t_ms-60_000-self.start_ms)//SLOT))
        anchor_slot=None if anchor_ms is None else max(0,(anchor_ms-self.start_ms)//SLOT)
        key=(end,anchor_slot)
        if key in self.cache:return self.cache[key]
        result=[]
        for label,length in [('day',96),('week',672),('sixty_day',5760)]:
            if end>=length:
                result.extend(zones_from_hist(self.prefix[end]-self.prefix[end-length],self.offset,label))
        session=(end//96)*96
        if end>session:
            result.extend(zones_from_hist(self.prefix[end]-self.prefix[session],self.offset,'session'))
        if anchor_slot is not None and end-anchor_slot>=16:
            result.extend(zones_from_hist(self.prefix[end]-self.prefix[anchor_slot],self.offset,'anchored'))
        output=(result,self.start_ms+end*SLOT)
        self.cache[key]=output
        return output


def context_features(m):
    def bars(freq):return m.resample(freq,label='right',closed='left').agg(dict(o='first',h='max',l='min',c='last',v='sum'))
    def expand(s):
        s=s.copy();s.index+=pd.Timedelta(minutes=1)
        return s.reindex(m.index,method='ffill')
    out=pd.DataFrame(index=m.index)
    for freq,label in [('1D','daily'),('4h','four_hour'),('1h','hour'),('15min','quarter')]:
        b=bars(freq);slow=b.c.ewm(span=20,min_periods=20,adjust=False).mean()
        out[label]=expand(np.sign(b.c-slow))
    b=bars('3min');tr=pd.concat([b.h-b.l,(b.h-b.c.shift()).abs(),(b.l-b.c.shift()).abs()],axis=1).max(axis=1)
    for k in ['o','h','l','c']:out['b_'+k]=expand(b[k])
    out['b_previous_close']=expand(b.c.shift())
    out['atr']=expand(tr.rolling(14).mean())
    for k in ['o','h','l','c']:out['m_'+k]=m[k].shift(2)
    q=bars('4h')
    # A swing anchor is recognized only after TWO following completed 4h bars.
    low=q.l.shift(2);high=q.h.shift(2)
    pivot=((low<q.l.shift(4))&(low<q.l.shift(3))&(low<q.l.shift(1))&(low<q.l)) | ((high>q.h.shift(4))&(high>q.h.shift(3))&(high>q.h.shift(1))&(high>q.h))
    anchor=pd.Series((q.index-pd.Timedelta(hours=12)).asi8//10**6,index=q.index).where(pivot).ffill()
    out['anchor_ms']=expand(anchor)
    out['decision']=(m.index.minute%3==1).astype(int)
    return out


def reaction(z, side, v):
    if side>0:
        return v['b_l']<=z.high and v['b_c']>z.high and v['b_c']>v['b_o'] and v['m_c']>v['m_o']
    return v['b_h']>=z.low and v['b_c']<z.low and v['b_c']<v['b_o'] and v['m_c']<v['m_o']


def choose_zone(zones,side,v):
    candidates=[z for z in zones if reaction(z,side,v)]
    def score(z):
        overlap=len({x.horizon for x in zones if x.low<=z.high and x.high>=z.low})
        return overlap,z.horizon in ('sixty_day','week'),-abs(v['b_c']-z.poc)
    return max(candidates,key=score) if candidates else None


def broken(zone,side,v):
    return (v['b_c']<zone.low and v['b_previous_close']<zone.low) if side>0 else (v['b_c']>zone.high and v['b_previous_close']>zone.high)


def direction(v):
    # Daily / 4h establish context; 1h must confirm; 15m confirms new risk.
    base=int(np.sign(v['daily']+v['four_hour']))
    return base if base and v['hour']==base and v['quarter']==base else 0
