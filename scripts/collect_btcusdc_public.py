"""Collect official public BTCUSDC archives and funding, without account access."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from zipfile import ZipFile
import hashlib
import io
import json
import urllib.request
import urllib.parse
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/historical/btcusdc_public_20260917'
OUT.mkdir(exist_ok=True)
API='https://fapi.binance.com'
ARCHIVE='https://data.binance.vision/data/futures/um/monthly'
END=1788220800000  # 2026-09-01T00:00:00Z, historical coverage only


def get(url):
    if not url.startswith((API+'/',ARCHIVE+'/')):
        raise ValueError('unapproved public source')
    with urllib.request.urlopen(url,timeout=30) as response:
        return response.read()


def save(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def archive(job):
    kind,month=job
    filename=f'BTCUSDC-1m-{month}.zip'
    url=f'{ARCHIVE}/{kind}/BTCUSDC/1m/{filename}'
    folder=OUT/kind;folder.mkdir(exist_ok=True)
    path=folder/filename
    result=dict(kind=kind,month=month,url=url,path=str(path.relative_to(ROOT)))
    try:
        checksum=get(url+'.CHECKSUM').decode().strip()
        raw=path.read_bytes() if path.exists() else get(url)
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=checksum.split()[0]:
            raise ValueError('official checksum mismatch; existing bytes not replaced')
        if not path.exists():path.write_bytes(raw)
        (folder/(filename+'.CHECKSUM')).write_text(checksum+'\n')
        with ZipFile(io.BytesIO(raw)) as z:
            with z.open(filename[:-4]+'.csv') as source:
                frame=pd.read_csv(source)
        required=['open_time','open','high','low','close','volume','close_time']
        if not set(required)<=set(frame):raise ValueError('unexpected schema')
        frame=frame.apply(pd.to_numeric,errors='raise')
        timestamp=frame.open_time.to_numpy(dtype=np.int64)
        delta=np.diff(timestamp)
        prices=frame[['open','high','low','close']].to_numpy()
        invalid=(~np.isfinite(prices).all(axis=1))|(prices<=0).any(axis=1)
        invalid|=(frame.high<frame[['open','close']].max(axis=1)-1e-8)|(frame.low>frame[['open','close']].min(axis=1)+1e-8)
        invalid|=(frame.close_time.to_numpy()!=timestamp+59999)|(timestamp%60000!=0)
        if kind=='klines':
            values=frame[['volume','quote_volume','count','taker_buy_volume','taker_buy_quote_volume']]
            invalid|=(~np.isfinite(values).all(axis=1))|(values<0).any(axis=1)
            invalid|=(frame.taker_buy_volume>frame.volume+1e-8)|(frame.taker_buy_quote_volume>frame.quote_volume+1e-6)
            invalid|=frame['count']!=np.floor(frame['count'])
        anomalies=np.flatnonzero(delta!=60000)
        start=pd.Timestamp(month+'-01',tz='UTC');end=start+pd.offsets.MonthBegin(1)
        in_month=(timestamp>=start.value//1000000)&(timestamp<end.value//1000000)
        result.update(sha256=digest,official_checksum=checksum,rows=len(frame),first_ms=int(timestamp[0]),last_ms=int(timestamp[-1]),
                      first=pd.to_datetime(timestamp[0],unit='ms',utc=True).isoformat(),
                      end_exclusive=pd.to_datetime(timestamp[-1]+60000,unit='ms',utc=True).isoformat(),
                      invalid_rows=int(invalid.sum()),outside_month=int((~in_month).sum()),
                      discontinuities=[dict(before_ms=int(timestamp[i]),after_ms=int(timestamp[i+1]),delta_ms=int(delta[i])) for i in anomalies],
                      complete_calendar_month=len(frame)==int((end-start).total_seconds()/60) and len(anomalies)==0 and bool(in_month.all()))
        result['status']='PASS' if not invalid.any() and not len(anomalies) and in_month.all() else 'QUALITY_REVIEW'
    except Exception as exc:
        result.update(status='FAILED',error=str(exc))
    print(kind,month,result['status'],result.get('rows'),flush=True)
    return result


def main():
    save(OUT/'collection_status.json',dict(status='RUNNING'))
    sources=[]
    for name,path in [('exchange_info','/fapi/v1/exchangeInfo'),('funding_info','/fapi/v1/fundingInfo'),('premium_index','/fapi/v1/premiumIndex?symbol=BTCUSDC')]:
        raw=get(API+path)
        (OUT/(name+'.json')).write_bytes(raw)
        sources.append(dict(name=name,url=API+path,sha256=hashlib.sha256(raw).hexdigest(),retrieved_at=datetime.now(timezone.utc).isoformat()))
    info=json.loads((OUT/'exchange_info.json').read_text())
    symbol=next(s for s in info['symbols'] if s['symbol']=='BTCUSDC')
    save(OUT/'contract.json',symbol)
    months=[str(p) for p in pd.period_range('2024-01','2026-08',freq='M')]
    with ThreadPoolExecutor(max_workers=4) as pool:
        records=list(pool.map(archive,[(kind,month) for kind in ['klines','markPriceKlines','indexPriceKlines'] for month in months]))
    boundary=[]
    for kind in ['klines','markPriceKlines','indexPriceKlines']:
        group=sorted([r for r in records if r['kind']==kind and 'first_ms' in r],key=lambda r:r['first_ms'])
        for a,b in zip(group,group[1:]):
            if b['first_ms']!=a['last_ms']+60000:
                boundary.append(dict(kind=kind,before=a['end_exclusive'],after=b['first']))
    funding=[];cursor=symbol['onboardDate'];pages=[]
    for page in range(20):
        params=urllib.parse.urlencode(dict(symbol='BTCUSDC',startTime=cursor,endTime=END-1,limit=1000))
        url=API+'/fapi/v1/fundingRate?'+params
        raw=get(url);values=json.loads(raw)
        if not isinstance(values,list):raise ValueError('funding response is not a list')
        target=OUT/f'funding_page_{page:02d}.json';target.write_bytes(raw)
        pages.append(dict(url=url,path=str(target.relative_to(ROOT)),sha256=hashlib.sha256(raw).hexdigest()))
        if not values:break
        if any(v['symbol']!='BTCUSDC' or not cursor<=v['fundingTime']<END for v in values):raise ValueError('funding symbol/time mismatch')
        times=[v['fundingTime'] for v in values]
        if times!=sorted(set(times)):raise ValueError('duplicate or reversed funding times')
        for v in values:
            if not np.isfinite(float(v['fundingRate'])) or not np.isfinite(float(v['markPrice'])) or float(v['markPrice'])<=0:raise ValueError('invalid funding values')
        funding.extend(values);cursor=times[-1]+1
        if len(values)<1000:break
    else:raise ValueError('funding pagination limit reached')
    save(OUT/'funding_history.json',funding)
    intervals=np.diff([v['fundingTime'] for v in funding])/3600000
    stats=dict(events=len(funding),first_ms=funding[0]['fundingTime'] if funding else None,last_ms=funding[-1]['fundingTime'] if funding else None,
               rate_min=min(float(v['fundingRate']) for v in funding) if funding else None,
               rate_max=max(float(v['fundingRate']) for v in funding) if funding else None,
               interval_hours_min=float(intervals.min()) if len(intervals) else None,interval_hours_max=float(intervals.max()) if len(intervals) else None,
               note='Observed intervals, not a claim that present funding cadence held historically.')
    result=dict(symbol='BTCUSDC',market='USD-M PERPETUAL',retrieved_at=datetime.now(timezone.utc).isoformat(),
                status='PASS_PUBLIC_DATA' if all(r['status']=='PASS' for r in records) and not boundary and funding else 'REVIEW_REQUIRED',
                coverage_end_exclusive='2026-09-01T00:00:00Z',sources=sources,archives=records,boundary_discontinuities=boundary,
                funding_sources=pages,funding_summary=stats,account_fields={'commission_rate':'UNKNOWN','leverage_brackets':'UNKNOWN','position_mode':'UNKNOWN','margin_mode':'UNKNOWN','available_balance':'UNKNOWN'},
                limitations=['Present filters are not historical filter history.','Account fees and margin require signed read-only evidence.',
                             'Minute data cannot verify three-second maker fallback fill probability.'])
    save(OUT/'manifest.json',result)
    save(OUT/'collection_status.json',dict(status='COMPLETE',result=result['status'],archives=len(records)))
    print(json.dumps(dict(status=result['status'],archives=len(records),boundary=boundary,funding=stats)),flush=True)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        save(OUT/'collection_status.json',dict(status='FAILED',reason=str(exc)))
        raise
