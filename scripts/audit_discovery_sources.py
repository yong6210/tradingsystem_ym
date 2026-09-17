"""Read-only provenance and unused flow-field quality audit; no return search."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request
from zipfile import ZipFile
import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'data/historical/btcusdt_2023_2026_complete/manifest.json').read_text())
output=ROOT/'reports/validation/strategy_discovery_20260917'
output.mkdir(exist_ok=True)

def check(record):
    path=Path(record['path'])
    url=f'https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1m/{path.name}.CHECKSUM'
    result={'file':path.name,'url':url}
    with path.open('rb') as stream:
        local_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    result['local_sha256']=local_hash
    result['matches_pinned_manifest']=local_hash==record['sha256']
    try:
        with urllib.request.urlopen(url,timeout=20) as response:
            raw=response.read().decode().strip()
        result['official_checksum_response']=raw
        result['matches_official']=raw.split()[0]==local_hash
    except Exception as exc:
        result['matches_official']=None
        result['source_error']=str(exc)
    with ZipFile(path) as archive, archive.open(path.stem+'.csv') as stream:
        frame=pd.read_csv(stream,header=None,usecols=[5,7,8,9,10],names=['volume','quote_volume','count','taker_buy_volume','taker_buy_quote_volume'])
    if str(frame.iloc[0]['volume'])=='volume':
        frame=frame.iloc[1:]
    frame=frame.astype(float)
    finite=np.isfinite(frame.to_numpy()).all(axis=1)
    negative=(frame<0).any(axis=1)
    too_large=(frame.taker_buy_volume>frame.volume+1e-8)|(frame.taker_buy_quote_volume>frame.quote_volume+1e-6)
    fractional=frame['count']!=np.floor(frame['count'])
    result.update(rows=len(frame),invalid_rows=int((~finite|negative|too_large|fractional).sum()),zero_volume_rows=int((frame.volume==0).sum()))
    return result

with ThreadPoolExecutor(max_workers=4) as pool:
    records=list(pool.map(check,manifest['files']))
result={'created_at_utc':datetime.now(timezone.utc).isoformat(),'status':'PASS' if all(r['matches_pinned_manifest'] and r['matches_official'] and not r['invalid_rows'] for r in records) else 'INCOMPLETE_OR_FAILED',
        'schema_reference':'https://github.com/binance/binance-public-data','files':records,'rows':sum(r['rows'] for r in records),
        'scope':'Official USD-M ZIP checksum and unused kline field bounds; not strategy evidence or BTCUSDC validation.',
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(output/'flow_data_audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='files'}))
