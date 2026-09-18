"""E026 fixed source/capital feasibility screen. Public GETs only, no orders."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
import numpy as np
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.carry_feasibility import parse_spot,quantity,path,verify_decimal
from scripts.run_direction_controls import save,load,digest,test_ids
from scripts.run_time_exit_policy import check_hashes,START,END


def main(out):
    out.mkdir(parents=True,exist_ok=False)
    sources={n:digest(ROOT/n) for n in ('scripts/run_carry_feasibility.py',
        'app/research/diagnostics/carry_feasibility.py','tests/test_carry_feasibility.py',
        'docs/research/experiments/E026_CARRY_FEASIBILITY.md',
        'app/research/data/btcusdc.py','app/research/data/minutes.py')}
    protected={}
    scheduled=ROOT/'reports/validation/e022_signal_boundary_20260919'
    protected.update(load(scheduled/'registration.json')['source_hashes'])
    for folder in ('e025_matched_fee_common_20260919','e025_matched_fee_extended_20260919_v2'):
        base=ROOT/'reports/validation'/folder
        for n,h in load(base/'verification.json')['artifact_hashes'].items():protected[str((base/n).relative_to(ROOT))]=h
    for f in scheduled.rglob('*'):
        if f.is_file():protected[str(f.relative_to(ROOT))]=digest(f)
    check_hashes(sources);check_hashes(protected)
    months=[str(p) for p in pd.period_range('2024-09','2026-08',freq='M')]
    suite=unittest.defaultTestLoader.loadTestsFromNames(('tests.test_carry_feasibility','tests.test_btcusdc_bundle'))
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='RETROSPECTIVE_DATA_AND_TWO_WALLET_FEASIBILITY_NOT_STRATEGY_BACKTEST',
        source_hashes=sources,protected_hashes=protected,test_ids=list(test_ids(suite)),
        start=START,end=END,spot_months=months,spot_fee_bps_assumptions=[0,2.5,10],
        scenarios=dict(base=dict(slippage_bps=2,extra_funding_bps=0),stress=dict(slippage_bps=5,extra_funding_bps=1)),
        capital=dict(spot_budget=400,futures_margin=500,minimum_outside_reserve=100),
        maximum_requests=49,max_response_bytes=1048576,max_total_bytes=16777216,
        timeout_seconds=20,automatic_retries=0,actual_orders=0))
    for n in sources:
        f=out/'source_snapshot'/n;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes((ROOT/n).read_bytes())
    with (out/'tests.log').open('x') as stream:r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(out/'tests.json',dict(executed=r.testsRun,failures=len(r.failures),errors=len(r.errors),skipped=len(r.skipped)))
    if not r.wasSuccessful() or r.skipped:raise ValueError('tests failed')
    raw_folder=out/'raw';raw_folder.mkdir();requests=[];total=0
    def get(url,name):
        nonlocal total
        if len(requests)>=49:raise ValueError('request cap')
        if not url.startswith(('https://data.binance.vision/data/spot/monthly/klines/BTCUSDC/1h/',
            'https://data-api.binance.vision/api/v3/exchangeInfo?symbol=BTCUSDC')):raise ValueError('source allowlist')
        record=dict(url=url,requested_at=datetime.now(timezone.utc).isoformat(),path=str((raw_folder/name).relative_to(ROOT)))
        requests.append(record)
        try:
            with urllib.request.urlopen(url,timeout=20) as response:
                raw=response.read(1048577);record['status']=response.status
            if len(raw)>1048576 or total+len(raw)>16777216:raise ValueError('response size cap')
            (raw_folder/name).write_bytes(raw);total+=len(raw)
            record.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),received_at=datetime.now(timezone.utc).isoformat())
            return raw
        except Exception as exc:
            record['error']=str(exc);raise
        finally:
            (out/'requests.json').write_text(json.dumps(dict(requests=requests,total_bytes=total),indent=2)+'\n')
    spot_frames=[];quality=[]
    for month in months:
        name='BTCUSDC-1h-'+month+'.zip'
        url='https://data.binance.vision/data/spot/monthly/klines/BTCUSDC/1h/'+name
        expected=get(url+'.CHECKSUM',name+'.CHECKSUM').decode().split()[0]
        raw=get(url,name)
        if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('official checksum mismatch')
        f,profile=parse_spot(raw,month);spot_frames.append(f);quality.append(dict(month=month,**profile))
        print('spot',month,profile['unit'],len(f),flush=True)
    info=json.loads(get('https://data-api.binance.vision/api/v3/exchangeInfo?symbol=BTCUSDC','spot_exchange_info.json'))
    contract=next(s for s in info['symbols'] if s['symbol']=='BTCUSDC')
    if contract['baseAsset']!='BTC' or contract['quoteAsset']!='USDC':raise ValueError('spot asset mismatch')
    spot=pd.concat(spot_frames)
    expected=pd.date_range(START,END,freq='h',inclusive='left')
    if not spot.index.equals(expected):raise ValueError('spot calendar coverage')
    print('Spot checks passed; loading frozen futures and funding.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
    bundle.require_complete_window(START,END)
    trade=bundle.trade.loc[(bundle.trade.index>=START)&(bundle.trade.index<END)]
    mark=bundle.mark.loc[(bundle.mark.index>=START)&(bundle.mark.index<END)]
    if not mark.index.equals(trade.index) or mark[['o','h','l','c']].isna().any().any():raise ValueError('mark coverage')
    future=trade.resample('h').agg(dict(o='first',c='last'))
    marks=mark.h.resample('h').max()
    if not future.index.equals(expected) or not marks.index.equals(expected):raise ValueError('join clocks')
    joined=pd.DataFrame(dict(spot_open=spot.o,spot_close=spot.c,future_open=future.o,future_close=future.c,mark_high=marks))
    if not np.isfinite(joined.to_numpy()).all():raise ValueError('joined nonfinite')
    save(out/'data_quality.json',dict(status='PASS_HOURLY_DESCRIPTIVE_JOIN_NOT_EXECUTION_DATA',
        grain='BTCUSDC_UTC_HOUR_OPEN',hours=len(joined),months=quality,join_expansion=0,missing_hours=0,
        spot_current_status=contract['status'],spot_filters=contract['filters'],
        historical_filter_schedule_verified=False,account_spot_fee_verified=False,
        limitations=['No bid/ask or two-leg execution ordering','Hourly highs are not liquidation engine replay',
            'Spot commission payment asset unknown','Current filters are not historical filters']))
    with (out/'joined_hourly.jsonl').open('x') as stream:
        for t,row in joined.iterrows():stream.write(json.dumps(dict(hour=t.isoformat(),**row.to_dict()))+'\n')
    q=quantity(float(spot.o.iloc[0]))
    from decimal import Decimal as D
    filters={f['filterType']:f for f in contract['filters']}
    lot=filters['LOT_SIZE']
    if D(str(q))%D(lot['stepSize']) or not D(lot['minQty'])<=D(str(q))<=D(lot['maxQty']):raise ValueError('current spot lot mismatch')
    minimum=filters.get('NOTIONAL',filters.get('MIN_NOTIONAL'))
    if minimum and D(str(q))*D(str(spot.o.iloc[0]))<D(minimum['minNotional']):raise ValueError('current spot minimum')
    results={};audits={}
    for scenario,slippage,extra in [('base',2,0),('stress',5,1)]:
        for fee in (0,2.5,10):
            key=scenario+'_spotfee_'+str(fee)
            result=path(joined,bundle.funding,q,fee,slippage,extra)
            audits[key]=verify_decimal(joined,bundle.funding,result)
            folder=out/key;folder.mkdir()
            for name in ('rows','funding'):
                with (folder/(name+'.jsonl')).open('x') as stream:
                    for row in result[name]:stream.write(json.dumps(row,allow_nan=False)+'\n')
            save(folder/'summary.json',result['summary'])
            results[key]=result['summary'];print(key,json.dumps(result['summary']),flush=True)
    check_hashes(sources);check_hashes(protected)
    blocked=any(r['first_nonpositive_isolated_equity'] is not None for r in results.values())
    save(out/'summary.json',dict(runs=results,decision='FIXED_NO_TRANSFER_CARRY_CAPITAL_REJECTED' if blocked else 'NO_ZERO_MARGIN_FAILURE_FOUND_FULL_MARGIN_EXECUTION_REVIEW_REQUIRED',
        selected_for_combination=False,forward_profitability_ready=False,actual_orders=0,operating_cost=None,
        spot_fee_user_verified=False,theoretical_terminal_values_are_not_feasible_strategy_returns=True))
    save(out/'verification.json',dict(status='PASS_SCOPED_DATA_AND_CAPITAL_DIAGNOSTIC',checks=audits,
        sources_unchanged=len(sources),protected_unchanged=len(protected),requests=len(requests),downloaded_bytes=total,
        artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve()
    try:main(out)
    except Exception as exc:
        if out.exists() and not (out/'failure.json').exists():save(out/'failure.json',dict(exception=type(exc).__name__,reason=str(exc)))
        raise
