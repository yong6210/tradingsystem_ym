"""Fetch a preregistered, previously unused September window from public GETs."""
import argparse
import hashlib
import json
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
API='https://fapi.binance.com'
ARCHIVE='https://data.binance.vision/data/futures/um/daily/klines/BTCUSDC/1m/'


def get(url):
    if not url.startswith((ARCHIVE,API+'/fapi/v1/fundingRate?')):
        raise ValueError('public GET allowlist only')
    with urllib.request.urlopen(url,timeout=30) as response:
        return response.read()


def main():
    p=argparse.ArgumentParser(); p.add_argument('--registration',required=True); p.add_argument('--output',required=True)
    args=p.parse_args()
    registration=json.loads(Path(args.registration).read_text())
    for name,digest in registration['files'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise ValueError(f'freeze mismatch: {name}')
    output=Path(args.output); output.mkdir(parents=True,exist_ok=False)
    begin=datetime.fromisoformat(registration['warmup_start'])
    end=datetime.fromisoformat(registration['end_exclusive'])
    days=[begin+timedelta(days=i) for i in range((end-begin).days)]
    def fetch(day):
        name=f'BTCUSDC-1m-{day:%Y-%m-%d}.zip'; url=ARCHIVE+name
        try:
            checksum=get(url+'.CHECKSUM').decode(); raw=get(url)
            digest=hashlib.sha256(raw).hexdigest()
            if digest!=checksum.split()[0]:
                raise ValueError('official checksum mismatch')
            (output/name).write_bytes(raw); (output/(name+'.CHECKSUM')).write_text(checksum)
            return dict(url=url,status='PASS',sha256=digest,path=str(output/name),bytes=len(raw))
        except Exception as exc:
            return dict(url=url,status='FAILED',error=str(exc))
    with ThreadPoolExecutor(max_workers=3) as pool:
        archives=list(pool.map(fetch,days))
    query=urllib.parse.urlencode(dict(symbol='BTCUSDC',startTime=int(begin.timestamp()*1000),endTime=int(end.timestamp()*1000)-1,limit=1000))
    url=API+'/fapi/v1/fundingRate?'+query
    try:
        raw=get(url); funding=json.loads(raw)
        if not funding or len(funding)>=1000 or any(r['symbol']!='BTCUSDC' for r in funding):
            raise ValueError('empty, truncated or wrong-symbol funding response')
        times=[int(r['fundingTime']) for r in funding]
        if times!=sorted(set(times)) or not all(int(begin.timestamp()*1000)<=t<int(end.timestamp()*1000) for t in times):
            raise ValueError('funding chronology/window mismatch')
        if times[0]-int(begin.timestamp()*1000)>8*3600000+1000 or int(end.timestamp()*1000)-times[-1]>8*3600000+1000 or any(b-a>8*3600000+1000 for a,b in zip(times,times[1:])):
            raise ValueError('funding coverage gap exceeds 8h')
        (output/'funding.json').write_bytes(raw)
        funding_result=dict(url=url,status='PASS',sha256=hashlib.sha256(raw).hexdigest(),rows=len(funding))
    except Exception as exc:
        funding_result=dict(url=url,status='FAILED',error=str(exc))
    manifest=dict(registration=str(Path(args.registration).resolve()),retrieved_at=datetime.now(timezone.utc).isoformat(),
                  archives=archives,funding=funding_result,
                  status='PASS' if all(x['status']=='PASS' for x in archives+[funding_result]) else 'BLOCKED')
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(status=manifest['status'],archives_passed=sum(x['status']=='PASS' for x in archives),
                         archives_total=len(archives),funding=funding_result),indent=2))


if __name__=='__main__':
    main()
