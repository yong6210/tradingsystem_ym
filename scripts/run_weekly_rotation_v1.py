#!/usr/bin/env python3
"""Small-capital weekly rotation research. Public data only; no order API."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import argparse, hashlib, json, shutil, urllib.request, concurrent.futures
from datetime import datetime, timezone
import pandas as pd
from app.research.diagnostics.pair_feasibility import parse_hour_archive
from app.research.diagnostics.weekly_rotation_v1 import signals, simulate

CONFIG = ROOT/'configs/research/e049_weekly_rotation_v1.json'
OUT = ROOT/'reports/validation/e049_weekly_rotation_20260919'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p, x): p.write_text(json.dumps(x, indent=2, allow_nan=False)+'\n')
def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Research/1.0'}), timeout=45) as r:
        return r.read()

def collect(c):
    raw=OUT/'raw'; raw.mkdir(exist_ok=True)
    months=pd.date_range(c['start'], c['end_exclusive'], freq='MS', inclusive='left').strftime('%Y-%m').tolist()
    jobs=[(s,m) for s in c['symbols'] for m in months]
    def one(job):
        s,m=job; name=f'{s}-1h-{m}.zip'; p=raw/name
        url=f'https://data.binance.vision/data/futures/um/monthly/klines/{s}/1h/{name}'
        old=ROOT/'reports/validation/e029_pair_feasibility_20260919/raw'/('klines_'+name)
        if not p.exists():
            if old.exists(): shutil.copyfile(old,p); shutil.copyfile(str(old)+'.CHECKSUM',str(p)+'.CHECKSUM')
            else: p.write_bytes(fetch(url)); Path(str(p)+'.CHECKSUM').write_bytes(fetch(url+'.CHECKSUM'))
        expected=Path(str(p)+'.CHECKSUM').read_text().split()[0]
        if sha(p)!=expected: raise ValueError('checksum '+name)
        f,quality=parse_hour_archive(p.read_bytes(),m)
        if quality['missing_hours']: raise ValueError('missing hours '+name)
        return s,f,{'file':str(p.relative_to(ROOT)),'sha256':sha(p),'url':url,'rows':len(f)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: parts=list(pool.map(one,jobs))
    frames={s:pd.concat([f for sym,f,_ in parts if sym==s],ignore_index=True) for s in c['symbols']}
    for s,f in frames.items():
        expected=pd.date_range(c['start'], c['end_exclusive'], freq='h', inclusive='left',tz='UTC').asi8//10**6
        if not (f.open_time.to_numpy()==expected).all(): raise ValueError('coverage '+s)
    contracts=raw/'exchange_info.json'
    if not contracts.exists(): contracts.write_bytes(fetch('https://fapi.binance.com/fapi/v1/exchangeInfo'))
    contracts_json=json.loads(contracts.read_text()); rules={}
    for s in c['symbols']:
        item=next(x for x in contracts_json['symbols'] if x['symbol']==s)
        filters={x['filterType']:x for x in item['filters']}
        lot=filters['MARKET_LOT_SIZE']; price=filters['PRICE_FILTER']
        rules[s]={k:float(lot[k]) for k in ['minQty','maxQty','stepSize']}
        rules[s].update(tickSize=float(price['tickSize']),minNotional=float(filters['MIN_NOTIONAL']['notional']))
    funding={}; inputs=[]
    paths={'BTCUSDC':'e028_carry_rule_replay_20260919/funding_inputs.jsonl','ETHUSDC':'e029_pair_feasibility_20260919/eth_funding.json','SOLUSDC':'e037_funding_opportunity_20260919_v2/sol_funding.json'}
    start=int(pd.Timestamp(c['start'],tz='UTC').timestamp()*1000); end=int(pd.Timestamp(c['end_exclusive'],tz='UTC').timestamp()*1000)
    for s,path in paths.items():
        p=ROOT/'reports/validation'/path; rows=[json.loads(l) for l in p.read_text().splitlines()] if p.suffix=='.jsonl' else json.loads(p.read_text())
        out=[]
        for x in rows:
            t=int(x.get('time_ms',x.get('fundingTime'))); rate=float(x.get('rate',x.get('fundingRate'))); mark=float(x.get('mark',x.get('markPrice')))
            if not start<=t<end or t%3600000>1000 or mark<=0: raise ValueError('funding boundary')
            out.append({'time_ms':t,'rate':rate,'mark':mark})
        if len(out)!=2190 or len({x['time_ms']//3600000 for x in out})!=2190: raise ValueError('funding coverage')
        funding[s]={x['time_ms']//3600000:x for x in out}; inputs.append({'file':str(p.relative_to(ROOT)),'sha256':sha(p)})
    save(OUT/'inputs.json',{'archives':[x for _,_,x in parts],'funding':inputs,'filters_sha256':sha(contracts),'rules':rules,'hours':len(next(iter(frames.values()))),'retrieved_at':datetime.now(timezone.utc).isoformat()})
    return frames,rules,funding

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--register',action='store_true'); args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True); c=json.loads(CONFIG.read_text())
    sources=[CONFIG,Path(__file__),ROOT/'app/research/diagnostics/weekly_rotation_v1.py',ROOT/'tests/test_weekly_rotation_v1.py']
    if args.register:
        if (OUT/'registration.json').exists(): raise SystemExit('Already registered; do not overwrite')
        save(OUT/'registration.json',{'registered_at':datetime.now(timezone.utc).isoformat(),'config':c,'sources':{str(p.relative_to(ROOT)):sha(p) for p in sources}})
        print('registered'); return
    reg=json.loads((OUT/'registration.json').read_text())
    if any(sha(ROOT/p)!=h for p,h in reg['sources'].items()): raise ValueError('registered source changed')
    if (OUT/'summary.json').exists(): raise SystemExit('Results already exist; do not overwrite')
    frames,rules,funding=collect(c); sig=signals(frames,c)
    save(OUT/'signals.json',sig); results=[]
    for model in ['rotation','btc_only']:
        for cost in c['cost_cases']:
            for op in c['monthly_operating_cost_cases']:
                for path in c['intrahour_paths']:
                    key=f'{model}_{cost}_op{op}_{path}'
                    summary,ledger,daily,trades=simulate(frames,rules,funding,sig,c,model,cost,op,path)
                    summary['case']=key; results.append(summary)
                    for kind,rows in [('ledger',ledger),('daily',daily),('trades',trades)]:
                        (OUT/f'{key}_{kind}.jsonl').write_text(''.join(json.dumps(x,allow_nan=False)+'\n' for x in rows))
    save(OUT/'summary.json',results)
    print(json.dumps(results,indent=2))
if __name__=='__main__': main()
