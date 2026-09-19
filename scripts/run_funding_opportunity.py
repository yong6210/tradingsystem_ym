"""E037 bounded public SOL funding retrieval and funding-only economics."""
import argparse
from datetime import datetime,timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import sys
import unittest
import urllib.request

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.research.diagnostics.funding_opportunity import analyze

START=1725148800000
END=1788220800000
INTERVAL=8*3600000


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,data):
    with p.open('x') as f:json.dump(data,f,indent=2,ensure_ascii=False,allow_nan=False)


def load_verified(folder,name):
    verification=json.loads((folder/'verification.json').read_text())
    expected=verification['artifacts'][name]
    p=folder/name
    if sha(p)!=expected:raise ValueError('changed original '+name)
    return p


def validate(events,symbol):
    if len(events)!=2190:raise ValueError(symbol+' unexpected funding event count')
    times=[]
    for i,event in enumerate(events):
        t=event['fundingTime'];r=D(str(event['fundingRate']));m=D(str(event['markPrice']))
        if event['symbol']!=symbol or type(t) is not int or not START<=t<END:
            raise ValueError('funding identity/time')
        if not r.is_finite() or not m.is_finite() or m<=0:raise ValueError('invalid numerical funding')
        if abs(t-(START+i*INTERVAL))>60000:raise ValueError('funding calendar gap/changed interval')
        times.append(t)
    if times!=sorted(set(times)):raise ValueError('duplicate/unordered funding')
    return dict(status='PASS',events=len(events),maximum_clock_deviation_ms=max(abs(t-(START+i*INTERVAL)) for i,t in enumerate(times)))


def main(out, reuse=None):
    out=out.resolve()
    out.mkdir(parents=True,exist_ok=False);(out/'raw').mkdir()
    sources={name:sha(ROOT/name) for name in [
        'scripts/run_funding_opportunity.py','app/research/diagnostics/funding_opportunity.py',
        'tests/test_funding_opportunity.py','docs/research/experiments/E037_FUNDING_OPPORTUNITY.md']}
    bp=load_verified(ROOT/'reports/validation/e028_carry_rule_replay_20260919','funding_inputs.jsonl')
    ep=load_verified(ROOT/'reports/validation/e029_pair_feasibility_20260919','eth_funding.json')
    inputs={str(p.relative_to(ROOT)):sha(p) for p in (bp,ep)}
    reused=[]
    if reuse is not None:
        reuse=reuse.resolve()
        request=json.loads((reuse/'requests.json').read_text())['requests'][0]
        expected_url=f'https://fapi.binance.com/fapi/v1/fundingRate?symbol=SOLUSDC&startTime={START}&endTime={END-1}&limit=1000'
        if request['url']!=expected_url or request['status']!=200:raise ValueError('reuse provenance')
        first=reuse/'raw/sol_funding_01.json'
        raw=first.read_bytes();reused=json.loads(raw)
        if len(raw)>1048576 or len(reused)!=1000:raise ValueError('unexpected recovered page')
        if [e['fundingTime'] for e in reused]!=sorted(set(e['fundingTime'] for e in reused)):raise ValueError('recovered page order')
        if any(e['symbol']!='SOLUSDC' or not START<=e['fundingTime']<END for e in reused):raise ValueError('recovered page bounds')
        for f in [first,reuse/'requests.json',reuse/'registration.json',reuse/'failure.json']:
            inputs[str(f.relative_to(ROOT))]=sha(f)
        (out/'raw/reused_sol_funding_01.json').write_bytes(raw)
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),source_hashes=sources,input_hashes=inputs,
        start_ms=START,end_exclusive_ms=END,symbols=['BTCUSDC','ETHUSDC','SOLUSDC'],
        max_requests=24,max_response_bytes=1048576,max_total_bytes=8388608,timeout_seconds=20,automatic_retries=0,
        classification='FUNDING_COMPONENT_ECONOMICS_NOT_ACCOUNT_OR_RISK_VALIDATION',btc_preview_known=True,
        lookback_settlements=21,hold_settlements=21,entry_threshold_sum='.0066',notional_per_leg=400,
        reused_successful_first_page=str(reuse) if reuse else None))
    for name in sources:
        p=out/'source_snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
    with (out/'tests.log').open('x') as f:
        result=unittest.TextTestRunner(stream=f,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_funding_opportunity'))
    if not result.wasSuccessful() or result.skipped:raise ValueError('focused tests failed')
    btc=[]
    for line in bp.read_text().splitlines():
        row=json.loads(line);btc.append(dict(symbol='BTCUSDC',fundingTime=row['time_ms'],fundingRate=row['rate'],markPrice=row['mark']))
    eth=json.loads(ep.read_text());sol=list(reused);cursor=reused[-1]['fundingTime']+1 if reused else START;receipts=[];total=0
    try:
        while cursor<END:
            if len(receipts)>=24:raise ValueError('request limit')
            url=f'https://fapi.binance.com/fapi/v1/fundingRate?symbol=SOLUSDC&startTime={cursor}&endTime={END-1}&limit=1000'
            record=dict(url=url,requested_at=datetime.now(timezone.utc).isoformat());receipts.append(record)
            with urllib.request.urlopen(url,timeout=20) as response:
                raw=response.read(1048577);record['status']=response.status
            if len(raw)>1048576:raise ValueError('response size limit')
            total+=len(raw)
            if total>8388608:raise ValueError('total size limit')
            path=out/'raw'/f'sol_funding_{len(receipts):02}.json';path.write_bytes(raw)
            record.update(received_at=datetime.now(timezone.utc).isoformat(),path=str(path.relative_to(ROOT)),bytes=len(raw),sha256=sha(path))
            batch=json.loads(raw)
            if not isinstance(batch,list):raise ValueError('unexpected public response')
            if not batch:break
            if any(row['fundingTime']<cursor or row['fundingTime']>=END for row in batch):raise ValueError('page boundary')
            if [r['fundingTime'] for r in batch]!=sorted(set(r['fundingTime'] for r in batch)):raise ValueError('page order')
            sol.extend(batch);cursor=batch[-1]['fundingTime']+1
            print('SOL public page',len(receipts),'rows',len(batch),flush=True)
            if len(batch)<1000:break
    except Exception as error:
        if receipts:receipts[-1]['error']=str(error)
        raise
    finally:save(out/'requests.json',dict(requests=receipts,bytes=total,reused_first_page=bool(reused)))
    save(out/'sol_funding.json',sol)
    quality={};results={}
    for symbol,events in [('BTCUSDC',btc),('ETHUSDC',eth),('SOLUSDC',sol)]:
        quality[symbol]=validate(events,symbol)
        results[symbol]=analyze(events)
        print(symbol,json.dumps({s:{k:v for k,v in r.items() if k!='causal_trades'} for s,r in results[symbol].items()}),flush=True)
    save(out/'data_quality.json',quality)
    fixed_btc={s:str(sum((max(D('.006')*D(e['markPrice'])*(D(e['fundingRate'])-extra),D(0)) for e in btc),D(0)))
               for s,extra in [('base',D(0)),('stress',D('.0001'))]}
    survivors=[symbol for symbol,r in results.items() if all(D(r[s]['causal_net_before_operations'])>0 for s in ['base','stress'])]
    save(out/'summary.json',dict(results=results,fixed_0006_btc_oracle_positive_funding_before_cost=fixed_btc,
        economic_screen_survivors=survivors,models_adopted=[],full_account_simulated=False,drawdown_5pct_verified=False,
        actual_orders=0,decision='ECONOMIC_CANDIDATE_NEEDS_FULL_ACCOUNT' if survivors else 'NO_FIXED_FILTER_CANDIDATE'))
    for name,h in {**sources,**inputs}.items():
        if sha(ROOT/name)!=h:raise ValueError('input changed')
    save(out/'verification.json',dict(status='PASS_COMPONENT_SCREEN_ONLY',focused_tests=result.testsRun,requests=len(receipts),
                                     source_hashes_unchanged=len(sources),input_hashes_unchanged=len(inputs),
                                     artifacts={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reuse-first-page',type=Path);a=parser.parse_args()
    try:main(a.output,a.reuse_first_page)
    except Exception as error:
        if a.output.exists() and not (a.output/'failure.json').exists():save(a.output/'failure.json',dict(type=type(error).__name__,reason=str(error)))
        raise
