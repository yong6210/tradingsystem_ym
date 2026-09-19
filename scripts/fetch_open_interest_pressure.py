"""Bounded E047 official daily OI archives; never uses keys or live orders."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from threading import Event,Lock
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_direction_controls import save,digest
OUT=ROOT/'data/historical/btcusdt_oi_20260919'
stop=Event();lock=Lock();total=0;requests=0


def fetch_day(date):
    global total,requests
    records=[];name=f'BTCUSDT-metrics-{date}.zip'
    for suffix,limit in [('',2*1024*1024),('.CHECKSUM',1024)]:
        path=OUT/(name+suffix);url='https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/'+path.name
        if path.exists():
            records.append(dict(file=path.name,status='CACHED_PREFLIGHT',sha256=digest(path),bytes=path.stat().st_size));continue
        if stop.is_set():return dict(date=date,status='STOPPED',requests=records)
        stamp=datetime.now(timezone.utc).isoformat()
        with lock:
            requests+=1
            if requests>1456:stop.set();raise ValueError('request budget')
        try:
            with urlopen(Request(url,headers={'User-Agent':'bounded-public-research/1.0'}),timeout=20) as response:
                raw=response.read(limit+1);status=response.status
            if len(raw)>limit:raise ValueError('response limit')
            with lock:
                total+=len(raw)
                if total>128*1024*1024:stop.set();raise ValueError('total size limit')
            with path.open('xb') as f:f.write(raw)
            records.append(dict(file=path.name,url=url,requested_at=stamp,status=status,bytes=len(raw),sha256=digest(path)))
        except Exception as error:
            code=error.code if isinstance(error,HTTPError) else None
            if code in (403,429):stop.set()
            records.append(dict(file=path.name,url=url,requested_at=stamp,status=code,error=type(error).__name__,message=str(error)))
            return dict(date=date,status='UNAVAILABLE',requests=records)
    expected=(OUT/(name+'.CHECKSUM')).read_text().split()
    if len(expected)!=2 or expected[1]!=name or expected[0]!=digest(OUT/name):
        stop.set();raise ValueError('official checksum mismatch '+date)
    return dict(date=date,status='VERIFIED',requests=records)


def main():
    dates=[(datetime(2024,8,29)+timedelta(days=i)).date().isoformat() for i in range(730)]
    if dates[-1]!='2026-08-28':raise ValueError('date scope')
    names=['scripts/fetch_open_interest_pressure.py','docs/research/experiments/E047_OPEN_INTEREST_PRESSURE.md']
    save(OUT/'acquisition_registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),dates=dates,
        max_new_requests=1456,workers=4,retries=0,timeout=20,max_total_bytes=128*1024*1024,
        source_hashes={n:digest(ROOT/n) for n in names},preflight_receipts_sha256=digest(OUT/'preflight_receipts.json')))
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(fetch_day,date):date for date in dates}
        for future in as_completed(jobs):
            try:results.append(future.result())
            except Exception as error:
                stop.set();results.append(dict(date=jobs[future],status='INVALID',error=str(error)))
            if len(results)%50==0:print('Completed',len(results),'of',len(dates),'bytes',total,flush=True)
    save(OUT/'manifest.json',dict(registered_dates=len(dates),new_requests=requests,new_bytes=total,stopped=stop.is_set(),
        verified_days=sum(r['status']=='VERIFIED' for r in results),days=sorted(results,key=lambda r:r['date']),
        source='OFFICIAL_REVISABLE_DAILY_ARCHIVE_NOT_POINT_IN_TIME_RECEIPTS'))
    print('DONE',requests,total,sum(r['status']=='VERIFIED' for r in results),flush=True)


if __name__=='__main__':main()
