"""E029 bounded public acquisition and pair sizing screen, without returns."""
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from scripts.run_carry_pair_drill import load,save,digest,check_hashes,test_ids
from app.research.diagnostics.pair_feasibility import parse_hour_archive,funding_profile,contract,size_pair,HOUR


def main():
    out=ROOT/'reports/validation/e029_pair_feasibility_20260919'
    out.mkdir(parents=True,exist_ok=False)
    names=('scripts/run_pair_feasibility.py','app/research/diagnostics/pair_feasibility.py',
        'tests/test_pair_feasibility.py','docs/research/experiments/E029_PAIR_FEASIBILITY.md','scripts/run_carry_pair_drill.py')
    sources={n:digest(ROOT/n) for n in names}
    previous=ROOT/'reports/validation/e028_carry_rule_replay_20260919'
    old=load(previous/'registration.json');protected=old['source_hashes']|old['protected_hashes']
    for folder in (previous,ROOT/'reports/validation/e028_carry_review_20260919'):
        receipt=load(folder/'verification.json')
        for n,h in receipt['artifacts'].items():protected[str((folder/n).relative_to(ROOT))]=h
        protected[str((folder/'verification.json').relative_to(ROOT))]=digest(folder/'verification.json')
        if 'report_path' in receipt:protected[receipt['report_path']]=receipt['report_sha256']
    check_hashes(sources);check_hashes(protected)
    start=pd.Timestamp('2024-09-01',tz='UTC');end=pd.Timestamp('2026-09-01',tz='UTC')
    start_ms=int(start.value//1_000_000);end_ms=int(end.value//1_000_000)
    months=[str(x) for x in pd.period_range('2024-09','2026-08',freq='M')]
    suite=unittest.defaultTestLoader.loadTestsFromNames(('tests.test_pair_feasibility',))
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='DATA_AND_CURRENT_FILTER_CAPITAL_SCREEN_NO_PNL_OR_SIGNAL_SELECTION',
        source_hashes=sources,protected_hashes=protected,test_ids=list(test_ids(suite)),
        symbols=['BTCUSDC','ETHUSDC'],start=start.isoformat(),end_exclusive=end.isoformat(),months=months,
        max_requests=110,max_response_bytes=4*1024*1024,max_total_bytes=32*1024*1024,
        max_runtime_seconds=600,timeout_seconds=20,automatic_retries=0,real_orders=0,
        fee_eth_verified=False,historical_filters_verified=False))
    for n in sources:
        dest=out/'source_snapshot'/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/n).read_bytes())
    with (out/'tests.log').open('x') as stream:r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(out/'tests.json',dict(executed=r.testsRun,failures=len(r.failures),errors=len(r.errors),skipped=len(r.skipped)))
    if not r.wasSuccessful() or r.skipped:raise ValueError('tests failed')
    raw=out/'raw';raw.mkdir();requests=[];total=0;began=time.monotonic()
    def get(url,name):
        nonlocal total
        if len(requests)>=110 or time.monotonic()-began>600:raise ValueError('request/runtime cap')
        if not url.startswith(('https://data.binance.vision/data/futures/um/monthly/klines/ETHUSDC/1h/',
            'https://data.binance.vision/data/futures/um/monthly/markPriceKlines/ETHUSDC/1h/',
            'https://fapi.binance.com/fapi/v1/fundingRate?symbol=ETHUSDC&',
            'https://fapi.binance.com/fapi/v1/exchangeInfo')):raise ValueError('source allowlist')
        record=dict(url=url,path=str((raw/name).relative_to(ROOT)),requested_at=datetime.now(timezone.utc).isoformat())
        requests.append(record)
        try:
            with urllib.request.urlopen(url,timeout=20) as response:body=response.read(4*1024*1024+1);record['status']=response.status
            if len(body)>4*1024*1024 or total+len(body)>32*1024*1024:raise ValueError('byte cap')
            (raw/name).write_bytes(body);total+=len(body)
            record.update(bytes=len(body),sha256=hashlib.sha256(body).hexdigest(),received_at=datetime.now(timezone.utc).isoformat())
            return body
        except Exception as exc:
            record['error']=str(exc);raise
        finally:save(out/'requests.json',dict(requests=requests,total_bytes=total))
    try:
        info=json.loads(get('https://fapi.binance.com/fapi/v1/exchangeInfo','exchange_info.json'))
        contracts={s['symbol']:contract(s) for s in info['symbols'] if s['symbol'] in ('BTCUSDC','ETHUSDC')}
        if set(contracts)!= {'BTCUSDC','ETHUSDC'}:raise ValueError('both contracts unavailable')
        save(out/'current_contracts.json',contracts)
        frames={'klines':[],'markPriceKlines':[]};profiles=[]
        for month in months:
            for kind in frames:
                name='ETHUSDC-1h-'+month+'.zip';url='https://data.binance.vision/data/futures/um/monthly/'+kind+'/ETHUSDC/1h/'+name
                stem=kind+'_'+name
                expected=get(url+'.CHECKSUM',stem+'.CHECKSUM').decode().split()[0]
                body=get(url,stem)
                if hashlib.sha256(body).hexdigest()!=expected:raise ValueError('official checksum mismatch')
                frame,profile=parse_hour_archive(body,month);frames[kind].append(frame)
                profiles.append(dict(month=month,kind=kind,**profile))
            print('Validated ETH',month,flush=True)
        funding=[];cursor=start_ms;page=0;exhausted=False
        while cursor<end_ms:
            if page>=12:raise ValueError('funding page cap')
            url=f'https://fapi.binance.com/fapi/v1/fundingRate?symbol=ETHUSDC&startTime={cursor}&endTime={end_ms-1}&limit=1000'
            rows=json.loads(get(url,f'funding_{page}.json'));page+=1
            if not isinstance(rows,list):raise ValueError('funding response schema')
            if not rows:exhausted=True;break
            if any(not cursor<=e['fundingTime']<end_ms for e in rows):raise ValueError('funding pagination bounds')
            funding.extend(rows)
            if rows[-1]['fundingTime']<cursor:raise ValueError('funding cursor stalled')
            cursor=rows[-1]['fundingTime']+1
            if len(rows)<1000:exhausted=True;break
        if not exhausted and cursor<end_ms:raise ValueError('funding pagination incomplete')
        fp=funding_profile(funding,start_ms,end_ms);save(out/'eth_funding.json',funding)
        expected=pd.date_range(start,end,freq='h',inclusive='left')
        trade=pd.concat(frames['klines']);mark=pd.concat(frames['markPriceKlines'])
        if trade.index.has_duplicates or mark.index.has_duplicates:raise ValueError('cross-month duplicate')
        btc=[json.loads(s) for s in (previous/'hourly_inputs.jsonl').read_text().splitlines()]
        if [r['time_ms'] for r in btc]!=list(expected.asi8//1_000_000):raise ValueError('BTC calendar mismatch')
        joined=[];sizes=[];reasons=Counter();passes=0;mismatch=[];checks=0
        for row,t in zip(btc,expected,strict=True):
            record=dict(time_ms=row['time_ms'],hour=t.isoformat(),btc_open=row['future_open'],btc_close=row['future_close'],
                btc_mark_open=row['mark_open'],btc_mark_close=row['mark_close'])
            if t not in trade.index or t not in mark.index:
                record['eth_data_missing']=True;joined.append(record);continue
            tr,mr=trade.loc[t],mark.loc[t]
            record.update(eth_open=str(tr.open),eth_close=str(tr.close),eth_mark_open=str(mr.open),eth_mark_close=str(mr.close),eth_data_missing=False)
            joined.append(record)
            s=size_pair(record['btc_open'],record['eth_open'],contracts['BTCUSDC'],contracts['ETHUSDC'])
            # Independent integer-grid arithmetic and direct constraints.
            b,e=D(str(record['btc_open'])),D(str(record['eth_open']));bc,ec=contracts['BTCUSDC'],contracts['ETHUSDC']
            qb=D(int(D(200)/(b*D('1.0005'))/bc['step']))*bc['step']
            qe=D(int(qb*b/e/ec['step']))*ec['step']
            if (qb,qe)!=(D(s['btc_qty']),D(s['eth_qty'])):raise ValueError('independent quantity mismatch')
            if s['eligible']:
                for q,p,c in ((qb,b,bc),(qe,e,ec)):
                    assert c['min_qty']<=q<=c['max_qty'] and q%c['step']==0
                    assert q*p*D('.9995')>=c['min_notional'] and q*p*D('1.0005')<=200
                    assert q*p*D('1.0005')*D('1.00025')<=400
                assert abs(qb*b-qe*e)<=D('.03')*max(qb*b,qe*e)
                assert max(qb*b,qe*e)*D('.01')+(qb*b+qe*e)*D('.0015')+1<=5
            checks+=1;passes+=s['eligible'];reasons.update(s['reasons']);mismatch.append(D(s['mismatch_fraction']))
            sizes.append(dict(hour=t.isoformat(),**s))
        for name,rows in (('joined_hourly',joined),('size_checks',sizes)):
            with (out/(name+'.jsonl')).open('x') as stream:
                for row in rows:stream.write(json.dumps(row,allow_nan=False)+'\n')
        missing=sum(r['eth_data_missing'] for r in joined)
        quality=dict(months=profiles,expected_hours=len(expected),joined_hours=len(joined),missing_pair_hours=missing,
            eth_funding=fp,official_checksums_passed=len(profiles),actual_quotes_or_partial_fills=False)
        save(out/'data_quality.json',quality)
        blocked=bool(missing or fp['schedule_or_gap_warnings'])
        summary=dict(decision='DATA_GAPS_REQUIRE_REVIEW' if blocked else 'CONDITIONAL_DATA_AND_ORDER_SIZING_READY_NOT_STRATEGY_ADOPTION',
            pair=['BTCUSDC','ETHUSDC'],price_hours=len(joined),complete_pair_hours=len(sizes),
            sizing_pass_hours=passes,sizing_rejected_hours=len(sizes)-passes,rejection_reasons=dict(reasons),
            maximum_nominal_mismatch_fraction=str(max(mismatch,default=D(0))),
            maximum_prepared_risk_usdc=str(max((D(s['prepared_risk_usdc']) for s in sizes),default=D(0))),
            independent_sizing_rows=checks,funding_events=len(funding),public_requests=len(requests),downloaded_bytes=total,
            historical_filters_verified=False,eth_account_fee_verified=False,actual_margin_mode_verified=False,
            signal_or_return_calculated=False,strategy_adopted=False,actual_orders=0,
            pair_hypothesis_frozen_before_eth_acquisition=True)
        save(out/'summary.json',summary);print(json.dumps(summary,indent=2),flush=True)
    except Exception as exc:
        save(out/'failure.json',dict(failed_at=datetime.now(timezone.utc).isoformat(),error=str(exc),
            requests=len(requests),downloaded_bytes=total,retried=False,classification='DATA_FEASIBILITY_NOT_PROFITABILITY_FAILURE'))
        raise
    finally:
        now=datetime.now(timezone.utc);public=ROOT/'reports/validation/e022_signal_boundary_20260919/public'
        save(out/'scheduled_observation.json',dict(checked_at=now.isoformat(),summary_present=(public/'summary.json').exists(),
            failure_present=(public/'failure.json').exists(),target_in_future=now<datetime.fromisoformat('2026-09-18T20:00:00+00:00'),modified=False))
        check_hashes(sources);check_hashes(protected)
        save(out/'verification.json',dict(status='FAIL_DATA_READINESS_PRESERVED' if (out/'failure.json').exists() else 'PASS_SCOPED_DATA_AND_SIZING',
            tests=r.testsRun,source_hashes_unchanged=len(sources),protected_hashes_unchanged=len(protected),
            artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':main()
