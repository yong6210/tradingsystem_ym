"""Bounded E029 REST cross-resolution repair; original evidence is immutable."""
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal as D
import json
from pathlib import Path
import sys
import unittest
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from scripts.run_carry_pair_drill import load,save,digest,check_hashes,test_ids
from app.research.diagnostics.pair_feasibility import parse_hour_archive,size_pair,HOUR

START=1782691200000
END=1782777600000


def parse(rows,start,end,step):
    if not isinstance(rows,list) or [r[0] for r in rows]!=list(range(start,end,step)):raise ValueError('REST exact coverage')
    result={}
    for row in rows:
        if len(row)!=12 or type(row[0])is not int or type(row[6])is not int or row[6]!=row[0]+step-1:raise ValueError('REST clock/schema')
        p=[D(str(v)) for v in row[1:5]]
        if not all(v.is_finite() and v>0 for v in p) or p[1]<max(p) or p[2]>min(p):raise ValueError('REST OHLC')
        result[row[0]]=dict(zip(('open','high','low','close'),p))
    return result


def compare(hourly,minute,start,end):
    checks=0
    for t in range(start,end,HOUR):
        subset=[minute[x] for x in range(t,t+HOUR,60000)]
        expected=dict(open=subset[0]['open'],high=max(r['high'] for r in subset),
            low=min(r['low'] for r in subset),close=subset[-1]['close'])
        for key,value in expected.items():
            if abs(hourly[t][key]-value)>D('.00000001'):raise ValueError('cross-resolution '+key)
            checks+=1
    return checks


def main():
    original=ROOT/'reports/validation/e029_pair_feasibility_20260919'
    out=ROOT/'reports/validation/e029_pair_mark_supplement_20260919';out.mkdir(exist_ok=False)
    reg=load(original/'registration.json');proof=load(original/'verification.json')
    protected=reg['source_hashes']|reg['protected_hashes']
    for n,h in proof['artifacts'].items():protected[str((original/n).relative_to(ROOT))]=h
    protected[str((original/'verification.json').relative_to(ROOT))]=digest(original/'verification.json')
    sources={n:digest(ROOT/n) for n in ('scripts/supplement_pair_mark.py','tests/test_pair_mark_supplement.py',
        'docs/research/experiments/E029_MARK_SUPPLEMENT.md')}
    suite=unittest.defaultTestLoader.loadTestsFromNames(('tests.test_pair_mark_supplement',))
    check_hashes(protected)
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),source_hashes=sources,
        protected_hashes=protected,test_ids=list(test_ids(suite)),start_ms=START,end_exclusive_ms=END,
        max_requests=2,max_total_bytes=2*1024*1024,automatic_retries=0,original_modified=False))
    for n in sources:
        dest=out/'source_snapshot'/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/n).read_bytes())
    with (out/'tests.log').open('x') as stream:r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    if not r.wasSuccessful() or r.skipped:raise ValueError('tests failed')
    requests=[];total=0
    try:
        def get(interval,start,end,limit):
            nonlocal total
            if len(requests)>=2:raise ValueError('request cap')
            url=f'https://fapi.binance.com/fapi/v1/markPriceKlines?symbol=ETHUSDC&interval={interval}&startTime={start}&endTime={end-1}&limit={limit}'
            item=dict(url=url,requested_at=datetime.now(timezone.utc).isoformat());requests.append(item)
            try:
                with urllib.request.urlopen(url,timeout=20) as response:body=response.read(1024*1024+1);item['status']=response.status
                if len(body)>1024*1024 or total+len(body)>2*1024*1024:raise ValueError('byte cap')
                path=out/('raw_'+interval+'.json');path.write_bytes(body);total+=len(body)
                item.update(path=str(path.relative_to(ROOT)),sha256=digest(path),bytes=len(body))
                return json.loads(body)
            except Exception as exc:item['error']=str(exc);raise
            finally:save(out/'requests.json',dict(requests=requests,total_bytes=total))
        hourly=parse(get('1h',START-HOUR,END+HOUR,100),START-HOUR,END+HOUR,HOUR)
        minute=parse(get('1m',START,END,1500),START,END,60000)
        checks=compare(hourly,minute,START,END)
        archive,_=parse_hour_archive((original/'raw/markPriceKlines_ETHUSDC-1h-2026-06.zip').read_bytes(),'2026-06')
        for t in (START-HOUR,END):
            row=archive.loc[pd.Timestamp(t,unit='ms',tz='UTC')]
            for key in ('open','high','low','close'):
                if abs(hourly[t][key]-D(str(row[key])))>D('.00000001'):raise ValueError('monthly overlap mismatch')
                checks+=1
        trade,_=parse_hour_archive((original/'raw/klines_ETHUSDC-1h-2026-06.zip').read_bytes(),'2026-06')
        rows=[json.loads(s) for s in (original/'joined_hourly.jsonl').read_text().splitlines()]
        missing=[x['time_ms'] for x in rows if x['eth_data_missing']]
        if missing!=list(range(START,END,HOUR)):raise ValueError('unexpected gap scope')
        for row in rows:
            if row['eth_data_missing']:
                t=row['time_ms'];tr=trade.loc[pd.Timestamp(t,unit='ms',tz='UTC')]
                row.update(eth_open=str(tr.open),eth_close=str(tr.close),eth_mark_open=str(hourly[t]['open']),
                    eth_mark_close=str(hourly[t]['close']),eth_data_missing=False,
                    mark_provenance='E029_REST_1H_RECONCILED_TO_1M_SUPPLEMENT')
        cc=load(original/'current_contracts.json')
        for c in cc.values():
            for key in ('step','min_qty','max_qty','min_notional'):c[key]=D(c[key])
        sizes=[];reason=Counter();independent=0
        for row in rows:
            s=size_pair(row['btc_open'],row['eth_open'],cc['BTCUSDC'],cc['ETHUSDC'])
            b,e=D(str(row['btc_open'])),D(row['eth_open']);bc,ec=cc['BTCUSDC'],cc['ETHUSDC']
            qb=D(int(200/(b*D('1.0005')*bc['step'])))*bc['step']
            qe=D(int(qb*b/(e*ec['step'])))*ec['step']
            assert (qb,qe)==(D(s['btc_qty']),D(s['eth_qty']))
            failure=[]
            for label,q,p,c in (('BTC',qb,b,bc),('ETH',qe,e,ec)):
                if not c['min_qty']<=q<=c['max_qty'] or q%c['step']:failure.append(label+'_quantity')
                if q*p*D('.9995')<c['min_notional']:failure.append(label+'_min_notional')
                if q*p*D('1.0005')>200:failure.append(label+'_leg_cap')
                if q*p*D('1.0005')*D('1.00025')>400:failure.append(label+'_initial_margin')
            if abs(qb*b-qe*e)>D('.03')*max(qb*b,qe*e):failure.append('notional_mismatch')
            if max(qb*b,qe*e)*D('.01')+(qb*b+qe*e)*D('.0015')+1>5:failure.append('prepared_risk')
            assert s['reasons']==failure and s['eligible']==(not failure)
            independent+=1;reason.update(failure);sizes.append(dict(hour=row['hour'],**s))
        for name,data in (('joined_hourly',rows),('size_checks',sizes)):
            with (out/(name+'.jsonl')).open('x') as stream:
                for row in data:stream.write(json.dumps(row)+'\n')
        ready=not load(original/'data_quality.json')['eth_funding']['schedule_or_gap_warnings']
        save(out/'summary.json',dict(status='VALIDATED_24_HOUR_SUPPLEMENT',checks=checks,filled_hours=24,
            full_pair_hours=len(rows),remaining_missing_hours=sum(x['eth_data_missing'] for x in rows),
            sizing_pass_hours=sum(s['eligible'] for s in sizes),sizing_rejected_hours=sum(not s['eligible'] for s in sizes),
            rejection_reasons=dict(reason),independent_sizing_rows=independent,
            maximum_mismatch_fraction=str(max(D(s['mismatch_fraction']) for s in sizes)),
            maximum_prepared_risk_usdc=str(max(D(s['prepared_risk_usdc']) for s in sizes)),
            data_ready_for_conditional_hourly_research=ready,real_execution_verified=False,
            signal_or_return_calculated=False,actual_orders=0,original_modified=False,
            requests=len(requests),downloaded_bytes=total))
        print(json.dumps(load(out/'summary.json'),indent=2))
    except Exception as exc:
        save(out/'failure.json',dict(error=str(exc),failed_at=datetime.now(timezone.utc).isoformat(),original_modified=False));raise
    finally:
        check_hashes(sources);check_hashes(protected)
        save(out/'verification.json',dict(status='FAIL_PRESERVED' if (out/'failure.json').exists() else 'PASS_BOUNDED_MARK_SUPPLEMENT',
            tests=r.testsRun,source_hashes_unchanged=len(sources),protected_hashes_unchanged=len(protected),
            artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':main()
