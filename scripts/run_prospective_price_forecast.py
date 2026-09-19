"""Q004 bounded manual lifecycle; public data only, no orders or scheduler."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from app.research.data.btcusdc import frame_from_csv
from app.research.diagnostics.prospective_price import frame_from_rows, make_panel, forecast, publication_window, score_unit, validate_funding_coverage

OUT = ROOT/'reports/validation/q004_prospective_price_forecast_20260919'
POLICY = ROOT/'configs/research/q004_prospective_price_forecast_v1.json'
OLD = ROOT/'reports/validation/e040_daily_flow_forecast_20260919/daily_features_and_targets.json'
AUGUST = ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'


def now(): return pd.Timestamp.now(tz='UTC')
def load(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, obj):
    import os
    with p.open('x') as f:
        json.dump(obj,f,indent=2,ensure_ascii=False,allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())


def check(reg):
    for name,h in reg['source_hashes'].items():
        if sha(ROOT/name)!=h: raise ValueError('frozen source mismatch: '+name)


class Public:
    def __init__(self, folder, limit, deadline=None):
        self.folder=folder; self.limit=limit; self.deadline=deadline; self.count=0

    def get(self,path,params=None):
        if self.count>=self.limit: raise ValueError('request budget')
        if self.deadline is not None and now()>=self.deadline: raise ValueError('request deadline')
        self.count+=1; name=f'{self.count:03d}'
        url='https://fapi.binance.com'+path
        if params: url+='?'+urllib.parse.urlencode(params)
        wall=time.time(); mono=time.monotonic()
        try:
            with urllib.request.urlopen(url,timeout=8) as r:
                raw=r.read(1048577); status=r.status
        except urllib.error.HTTPError as e:
            raw=e.read(1048577); status=e.code
        except Exception as e:
            raw=json.dumps(dict(error=type(e).__name__)).encode(); status=None
        end=time.time(); elapsed=time.monotonic()-mono
        with (self.folder/(name+'.raw.json')).open('xb') as f:f.write(raw)
        receipt=dict(url=url,status=status,requested_epoch=wall,received_epoch=end,
            elapsed_seconds=elapsed,wall_monotonic_drift_seconds=(end-wall)-elapsed,
            sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
        save(self.folder/(name+'.receipt.json'),receipt)
        if status!=200 or len(raw)>1048576:raise ValueError('public request failed')
        if abs(receipt['wall_monotonic_drift_seconds'])>.1:raise ValueError('clock drift')
        if self.deadline is not None and now()>=self.deadline:raise ValueError('response deadline')
        return json.loads(raw),receipt

    def clock(self):
        obj,r=self.get('/fapi/v1/time')
        offset=obj['serverTime']/1000-(r['requested_epoch']+r['received_epoch'])/2
        if abs(offset)>1 or r['elapsed_seconds']>3:raise ValueError('clock offset/RTT')
        return obj['serverTime'],dict(offset_seconds=offset,round_trip_seconds=r['elapsed_seconds'])

    def minutes(self,start,end,max_pages=120):
        rows=[]; a=int(start.timestamp()*1000); stop=int(end.timestamp()*1000)
        for _ in range(max_pages):
            if a>=stop:break
            finish=min(stop,a+1500*60000)
            page,_=self.get('/fapi/v1/klines',dict(symbol='BTCUSDC',interval='1m',startTime=a,endTime=finish-1,limit=1500))
            frame_from_rows(page,a,finish)
            rows+=page; a=finish
        if a!=stop:raise ValueError('tail page budget')
        return frame_from_rows(rows,int(start.timestamp()*1000),stop)


def date_boundary(value,policy):
    b=pd.Timestamp(value,tz='UTC')
    first=pd.Timestamp(policy['first_boundary_utc'])
    if b!=b.floor('D') or not first<=b<first+pd.Timedelta(days=policy['calendar_days']):raise ValueError('boundary outside registration')
    return b


def register():
    if OUT.exists():raise ValueError('registration exists')
    policy=load(POLICY)
    if now()>=pd.Timestamp(policy['first_boundary_utc']):raise ValueError('first boundary already passed')
    prior=load(ROOT/'reports/validation/q003_forecast_expectation_audit_20260919/registration.json')
    protected=prior['frozen_hashes']
    for name,h in protected.items():
        if sha(ROOT/name)!=h:raise ValueError('old evidence mismatch: '+name)
    names=['app/research/diagnostics/prospective_price.py','app/research/diagnostics/daily_flow_forecast.py',
        'app/research/data/btcusdc.py','app/research/data/minutes.py',
        'scripts/run_prospective_price_forecast.py','tests/test_prospective_price.py',
        'docs/research/experiments/Q004_PROSPECTIVE_FORECAST.md',str(POLICY.relative_to(ROOT)),str(OLD.relative_to(ROOT)),str(AUGUST.relative_to(ROOT))]
    manifest=load(ROOT/'data/historical/btcusdc_public_20260917/manifest.json')
    archive=next(r for r in manifest['archives'] if r['path']==str(AUGUST.relative_to(ROOT)))
    if sha(AUGUST)!=archive['sha256']:raise ValueError('archive hash')
    OUT.mkdir()
    save(OUT/'registration.json',dict(registered_at_utc=now().isoformat(),policy=policy,
        source_hashes={n:sha(ROOT/n) for n in names},protected_hashes=protected,
        versions=dict(python=sys.version,numpy=np.__version__,pandas=pd.__version__),
        registered_before_first_outcome=True,automatic_schedule_created=False))
    tested=subprocess.run([sys.executable,'-m','unittest','tests.test_prospective_price','-v'],cwd=ROOT,capture_output=True,text=True)
    with (OUT/'tests.log').open('x') as f:f.write(tested.stdout+tested.stderr)
    if tested.returncode:raise ValueError(tested.stderr)
    save(OUT/'ready.json',dict(tests='PASS',registration_sha256=sha(OUT/'registration.json'),tests_sha256=sha(OUT/'tests.log')))
    print('Q004 registered and tested before first boundary',flush=True)


def prepare(day,b,reg):
    if now()>=b:raise ValueError('preparation must finish before boundary')
    folder=day/'prepare';folder.mkdir()
    rest=Public(folder,reg['policy']['limits']['prepare_requests'],min(b,now()+pd.Timedelta(seconds=180)))
    server,clock=rest.clock(); end=pd.Timestamp(server,unit='ms',tz='UTC').floor('min')
    base=frame_from_csv(AUGUST.read_bytes(),AUGUST.stem+'.csv')
    tail=rest.minutes(pd.Timestamp('2026-09-01T00:00:00Z'),end)
    minutes=pd.concat([base,tail])
    if minutes.index.has_duplicates or not (np.diff(minutes.index.asi8)==60000_000_000).all():raise ValueError('warmup gap')
    p=folder/'minutes.csv';minutes.to_csv(p,index_label='time')
    if now()>=b:raise ValueError('late preparation')
    save(folder/'summary.json',dict(status='PREPARED_NOT_PUBLISHED',boundary=b.isoformat(),completed_at_utc=now().isoformat(),
        minutes=len(minutes),end_exclusive=end.isoformat(),clock=clock,requests=rest.count,
        files={x.name:sha(x) for x in folder.iterdir() if x.is_file()}))
    print(json.dumps(dict(status='PREPARED',end_exclusive=end.isoformat(),minutes=len(minutes),requests=rest.count)),flush=True)


def publish(day,b,reg):
    state=publication_window(now(),b)
    if state!='OPEN':
        if state=='MISSED' and not (day/'missed.json').exists():save(day/'missed.json',dict(status='MISSED_NO_RETROSPECTIVE_PREDICTION',checked_at_utc=now().isoformat()))
        raise ValueError('publication window '+state)
    folder=day/'publish';folder.mkdir()
    started_wall=time.time();started_mono=time.monotonic()
    prep=load(day/'prepare/summary.json')
    if prep['boundary']!=b.isoformat():raise ValueError('wrong prepared date')
    for name,h in prep['files'].items():
        if sha(day/'prepare'/name)!=h:raise ValueError('prepared input mismatch')
    rest=Public(folder,reg['policy']['limits']['publish_requests'],b+pd.Timedelta(seconds=49))
    server,clock=rest.clock()
    if server<int(b.timestamp()*1000)+5000:raise ValueError('server boundary not complete')
    minutes=pd.read_csv(day/'prepare/minutes.csv',index_col='time',parse_dates=['time'])
    minutes.index=pd.to_datetime(minutes.index,utc=True)
    tail=rest.minutes(pd.Timestamp(prep['end_exclusive']),b,max_pages=4)
    minutes=pd.concat([minutes,tail])
    panel,overlap=make_panel(load(OLD)['data'],minutes,b)
    funding,_=rest.get('/fapi/v1/fundingRate',dict(symbol='BTCUSDC',startTime=int((b-pd.Timedelta(days=2)).timestamp()*1000),endTime=int(b.timestamp()*1000)-1,limit=1000))
    result=forecast(panel,b,funding)
    if len(funding)>=1000:raise ValueError('funding pagination ambiguity')
    if abs((time.time()-started_wall)-(time.monotonic()-started_mono))>.1:raise ValueError('publication clock drift')
    _,final_clock=rest.clock()
    if publication_window(now(),b)!='OPEN':raise ValueError('late forecast calculation')
    minutes.to_csv(folder/'minutes.csv',index_label='time')
    payload=dict(result,created_at_utc=now().isoformat(),registration_sha256=sha(OUT/'registration.json'),
        scope=reg['policy']['scope'],overlap_value_checks=overlap,clock=clock,final_clock=final_clock,
        requests=rest.count,input_hashes={p.name:sha(p) for p in folder.iterdir() if p.is_file()},
        outcome_observed=False,actual_order=False)
    save(folder/'forecast.json',payload)
    committed=now()
    status='PUBLISHED_BEFORE_TARGET' if publication_window(committed,b)=='OPEN' else 'LATE_INVALID'
    save(folder/'publication_receipt.json',dict(status=status,committed_at_utc=committed.isoformat(),
        forecast_sha256=sha(folder/'forecast.json'),target_start_utc=result['entry_time']))
    print(json.dumps(dict(status=status,boundary=b.isoformat(),prediction_bps=result['prediction_bps'],threshold_bps=result['threshold_bps'],
        selectors=result['selectors'],controls=result['controls'],committed_at_utc=committed.isoformat()),indent=2),flush=True)
    if status!='PUBLISHED_BEFORE_TARGET':raise ValueError('late durable publication')


def score(day,b,reg):
    if now()<b+pd.Timedelta(days=1,minutes=1):raise ValueError('outcome minute not complete')
    folder=day/'score';folder.mkdir()
    record=load(day/'publish/forecast.json');receipt=load(day/'publish/publication_receipt.json')
    if receipt['status']!='PUBLISHED_BEFORE_TARGET' or publication_window(pd.Timestamp(receipt['committed_at_utc']),b)!='OPEN':raise ValueError('not a prospective forecast')
    if receipt['forecast_sha256']!=sha(day/'publish/forecast.json') or record['registration_sha256']!=sha(OUT/'registration.json'):raise ValueError('forecast binding')
    for name,h in record['input_hashes'].items():
        if sha(day/'publish'/name)!=h:raise ValueError('published input mismatch')
    rest=Public(folder,6,now()+pd.Timedelta(seconds=60));server,clock=rest.clock()
    if server<int((b+pd.Timedelta(days=1,minutes=1)).timestamp()*1000):raise ValueError('server outcome not complete')
    entry=b+pd.Timedelta(minutes=1);exit=b+pd.Timedelta(days=1)
    a=rest.minutes(entry,entry+pd.Timedelta(minutes=1));z=rest.minutes(exit,exit+pd.Timedelta(minutes=1))
    funding,_=rest.get('/fapi/v1/fundingRate',dict(symbol='BTCUSDC',startTime=int((entry-pd.Timedelta(days=1)).timestamp()*1000),endTime=int((exit+pd.Timedelta(minutes=1)).timestamp()*1000)-1,limit=1000))
    if len(funding)>=1000:raise ValueError('funding pagination')
    validate_funding_coverage(funding,int(entry.timestamp()*1000),int(exit.timestamp()*1000))
    price_a,price_b=float(a.iloc[0].o),float(z.iloc[0].o)
    y=(price_b/price_a-1)*10000
    events={}
    for name,side in record['selectors'].items():
        events[name]={cost:score_unit(price_a,price_b,side,funding,int(entry.timestamp()*1000),int(exit.timestamp()*1000),
            p['fee_bps'],p['slippage_bps'],p['extra_funding_bps_per_settlement']) for cost,p in reg['policy']['cost_scenarios'].items()}
    save(folder/'outcome.json',dict(status='UNIT_EVENT_PROXY_NOT_ACCOUNT_OR_REAL_FILL',boundary=b.isoformat(),
        scored_at_utc=now().isoformat(),target_bps=y,prediction_errors={k:p-y for k,p in dict(PRICE=record['prediction_bps'],**record['controls']).items()},
        events=events,forecast_sha256=receipt['forecast_sha256'],clock=clock,requests=rest.count,
        artifacts={p.name:sha(p) for p in folder.iterdir() if p.is_file()}))
    print(json.dumps(load(folder/'outcome.json'),indent=2))


def status(reg):
    states=[];first=pd.Timestamp(reg['policy']['first_boundary_utc']);today=now()
    for i in range(reg['policy']['calendar_days']):
        b=first+pd.Timedelta(days=i);day=OUT/b.strftime('%Y-%m-%d')
        p=day/'publish/publication_receipt.json';s=day/'score/outcome.json'
        value='FUTURE' if today<b else 'PENDING_WINDOW' if today<=b+pd.Timedelta(seconds=50) else 'MISSED_NO_PUBLICATION'
        if p.exists():value=load(p)['status']
        if s.exists():value='SCORED_UNIT_EVENT_PROXY'
        states.append(dict(boundary=b.isoformat(),status=value))
    print(json.dumps(dict(checked_at_utc=today.isoformat(),automatic_schedule_created=False,
        counts={k:sum(x['status']==k for x in states) for k in sorted({x['status'] for x in states})},
        started=[x for x in states if x['status']!='FUTURE']),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['register','prepare','publish','score','status']);p.add_argument('--boundary');a=p.parse_args()
    if a.mode=='register':register();sys.exit()
    reg=load(OUT/'registration.json');check(reg)
    if load(OUT/'ready.json')['registration_sha256']!=sha(OUT/'registration.json'):raise ValueError('registration not verified')
    if a.mode=='status':status(reg);sys.exit()
    b=date_boundary(a.boundary,reg['policy']);day=OUT/b.strftime('%Y-%m-%d');day.mkdir(exist_ok=True)
    try:
        dict(prepare=prepare,publish=publish,score=score)[a.mode](day,b,reg)
    except Exception as e:
        path=day/(a.mode+'_failure.json')
        if not path.exists():save(path,dict(failed_at_utc=now().isoformat(),type=type(e).__name__,reason=str(e)))
        raise
