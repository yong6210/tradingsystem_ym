"""One documented unauthenticated, bounded five-minute archival sample request."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
import zlib

ROOT=Path(__file__).resolve().parents[1]


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out=ROOT/'reports/validation/e031_raw_sample_access_20260919';out.mkdir(exist_ok=False)
    save=lambda name,obj:(out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    filters=[dict(channel=c,symbols=['btcusdc']) for c in ('depth','depthSnapshot','aggTrade','bookTicker','markPrice')]
    query=dict(**{'from':'2024-09-01T00:00:00.000Z'},offset=0,sliceSize=5,filters=json.dumps(filters,separators=(',',':')),compression='gzip')
    url='https://api.tardis.dev/v1/data-feeds/binance-futures?'+urlencode(query)
    save('registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),source_sha256=sha(Path(__file__)),url=url,
        purpose='Raw schema/disconnect/snapshot fitness only; no signals, PnL or sample selection',
        rationale='Documented first-day free raw API includes disconnect markers absent from daily CSV; existing CSV403 retained',
        period_start='2024-09-01T00:00:00Z',period_end_exclusive='2024-09-01T00:05:00Z',
        max_requests=1,retries=0,authentication=False,paid_access=False,compressed_cap_bytes=8388608,
        decoded_cap_bytes=33554432,socket_timeout_seconds=20,read_deadline_seconds=45,
        references=['https://docs.tardis.dev/api/http-api-reference.md','https://docs.tardis.dev/downloadable-csv-files/api.md']))
    started=time.monotonic();body=bytearray();result=dict(requests=1,retries=0,paid_access=False,actual_orders=0)
    try:
        try:
            response=urlopen(Request(url,headers={'Accept-Encoding':'gzip','User-Agent':'trading-research-data-fitness/1.0'}),timeout=20)
        except HTTPError as error:
            response=error
        with response:
            result['http_status']=response.status
            result['headers']={k:v for k,v in response.headers.items() if k.lower() in ('content-type','content-encoding','content-length','x-slice-size','x-suggested-slice-size')}
            limit=8388608 if response.status==200 else 8192
            while len(body)<limit:
                if time.monotonic()-started>45: raise TimeoutError('bounded read deadline')
                chunk=response.read(min(65536,limit-len(body)))
                if not chunk: break
                body.extend(chunk)
            else:
                raise ValueError('response reached bounded size; completeness unverified')
        result['status']='HTTP_SUCCESS_CONTENT_UNVERIFIED' if result['http_status']==200 else 'ACCESS_FAILED_NO_RETRY'
        if result['http_status']==200:
            if bytes(body[:2])==b'\x1f\x8b':
                decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
                decoded=decoder.decompress(body,33554433)
                if len(decoded)>33554432 or not decoder.eof or decoder.unused_data:
                    raise ValueError('decoded limit or unsupported/incomplete gzip members')
            else: decoded=bytes(body)
            (out/'raw.ndjson').write_bytes(decoded)
            result['decoded_bytes']=len(decoded)
            result['status']='COMPLETE_RESPONSE_PENDING_SCHEMA_AND_REPLAY'
    except Exception as error:
        result.update(status='FAILED_BOUNDED_REQUEST_OR_DECODE',error_type=type(error).__name__,reason=str(error))
    (out/'response.bin').write_bytes(body)
    result.update(response_bytes=len(body),elapsed_seconds=time.monotonic()-started,
                  ended_at=datetime.now(timezone.utc).isoformat())
    save('result.json',result)
    save('verification.json',dict(source_sha256=sha(Path(__file__)),artifacts={p.name:sha(p) for p in out.iterdir() if p.is_file()}))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
