"""Register, fetch fixed eight short archives, and run the S06B event diagnostic."""
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal as D
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen,Request
from urllib.parse import urlencode
from urllib.error import HTTPError
import unittest
import zlib

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.audit_microstructure_fitness import load,save,sha,check,lines
from scripts.audit_microstructure_raw_sample import timestamp_ns
from scripts.audit_flow_events import verify
from app.research.diagnostics.flow_absorption import grid_from_raw,events

DATES=['2024-10-01','2025-01-01','2025-04-01','2025-07-01','2025-10-01','2026-01-01','2026-04-01','2026-07-01']


def fetch(date,folder):
    filters=[dict(channel=c,symbols=['btcusdc']) for c in ('depth','depthSnapshot','aggTrade','bookTicker','markPrice')]
    url='https://api.tardis.dev/v1/data-feeds/binance-futures?'+urlencode(dict(**{'from':date+'T00:00:00.000Z'},offset=0,sliceSize=10,compression='gzip',filters=json.dumps(filters,separators=(',',':'))))
    start=time.monotonic();raw=bytearray();result=dict(url=url,requests=1,retries=0)
    try:
        try:response=urlopen(Request(url,headers={'Accept-Encoding':'gzip','User-Agent':'trading-fixed-flow-diagnostic/1.0'}),timeout=20)
        except HTTPError as exc:response=exc
        with response:
            result['http_status']=response.status
            result['headers']={k:v for k,v in response.headers.items() if k.lower() in ('content-type','content-encoding','content-length','x-slice-size')}
            limit=8*1024**2 if response.status==200 else 8192
            while len(raw)<limit:
                if time.monotonic()-start>45:raise TimeoutError('bounded read deadline')
                chunk=response.read(min(65536,limit-len(raw)))
                if not chunk:break
                raw.extend(chunk)
            else:raise ValueError('response size cap')
        if result['http_status']!=200:raise ValueError('HTTP access failure')
        if bytes(raw[:2])!=b'\x1f\x8b':raise ValueError('expected registered gzip response')
        decoder=zlib.decompressobj(16+zlib.MAX_WBITS);decoded=decoder.decompress(raw,32*1024**2+1)
        if len(decoded)>32*1024**2 or not decoder.eof or decoder.unused_data:raise ValueError('gzip limit/completeness/members')
        (folder/'raw.ndjson').write_bytes(decoded)
        result.update(status='COMPLETE_RESPONSE',decoded_bytes=len(decoded))
    except Exception as exc:result.update(status='FAILED_NO_RETRY',error_type=type(exc).__name__,reason=str(exc))
    (folder/'response.bin').write_bytes(raw);result.update(response_bytes=len(raw),elapsed_seconds=time.monotonic()-start)
    save(folder/'access.json',result);return result


def main():
    now=datetime.now(timezone.utc)
    if datetime.fromisoformat('2026-09-18T19:59:00+00:00')<=now<datetime.fromisoformat('2026-09-18T20:02:00+00:00'):
        raise ValueError('E022 observation protected time')
    base=ROOT/'reports/validation';out=base/'e032_flow_absorption_20260919';out.mkdir(exist_ok=False)
    old=load(base/'e031_microstructure_fitness_20260919/registration.json');protected=old['protected_hashes']|old['input_hashes']|old['source_hashes']
    for directory in ['e030_pair_account_20260919','e031_raw_sample_access_20260919','e031_raw_sample_audit_20260919']:
        folder=base/directory;proof=load(folder/'verification.json');check(proof['artifacts'],folder)
        protected.update({str((folder/n).relative_to(ROOT)):h for n,h in proof['artifacts'].items()})
    check(protected)
    names=['docs/research/experiments/E032_FLOW_ABSORPTION.md','app/research/diagnostics/flow_absorption.py','app/research/data/local_order_book.py',
        'scripts/run_flow_absorption.py','scripts/audit_flow_events.py','scripts/audit_microstructure_raw_sample.py','scripts/audit_microstructure_fitness.py','tests/test_flow_absorption.py']
    sources={n:sha(ROOT/n) for n in names};fundpath=base/'e028_carry_rule_replay_20260919/funding_inputs.jsonl';funding=lines(fundpath)
    for date in DATES:
        start=timestamp_ns(date+'T00:00:00Z')//10**6
        if any(start+60000<=f['time_ms']<start+600000 for f in funding):raise ValueError('funding event inside fixed diagnostic window')
    save(out/'registration.json',dict(registered_at=now.isoformat(),source_hashes=sources,protected_hashes=protected,
        input_hashes={str(fundpath.relative_to(ROOT)):sha(fundpath)},dates=DATES,minutes_per_date=10,requests_max=8,retries=0,
        account_backtest=False,classification='FIXED_HYPOTHESIS_EVENT_AND_COST_FEASIBILITY_NOT_CONFIRMATORY',actual_orders=0))
    snap=out/'source_snapshot'
    for n in names:
        p=snap/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/n).read_bytes())
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_flow_absorption')
    with (out/'tests.log').open('w') as f: test=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    save(out/'tests.json',dict(executed=test.testsRun,failures=len(test.failures),errors=len(test.errors),skipped=len(test.skipped)))
    if not test.wasSuccessful() or test.skipped:raise ValueError('registered tests failed')
    results={};all_events=[];total_compressed=total_decoded=0
    for date in DATES:
        check(sources);folder=out/date;folder.mkdir();print('Fetching fixed interval',date,flush=True)
        access=fetch(date,folder);total_compressed+=access['response_bytes'];total_decoded+=access.get('decoded_bytes',0)
        if total_compressed>64*1024**2 or total_decoded>256*1024**2:raise ValueError('total cap')
        if access['status']!='COMPLETE_RESPONSE':results[date]=dict(status='ACCESS_FAILED',access=access);continue
        try:
            start=timestamp_ns(date+'T00:00:00Z');grid,quality=grid_from_raw(folder/'raw.ndjson',start,start+600*10**9,timestamp_ns)
            cohort=events(grid);audit=verify(grid,cohort)
            for key,values in [('grid',grid),('events',cohort)]:
                (folder/(key+'.jsonl')).write_text(''.join(json.dumps(x)+'\n' for x in values))
            save(folder/'independent_audit.json',audit);save(folder/'quality.json',quality)
            r=dict(status='COMPLETE_SCOPED_EVENT_DIAGNOSTIC',quality=quality,events=len(cohort),candidate_events=sum(e['candidate'] for e in cohort))
            all_events.extend(dict(date=date,**e) for e in cohort)
        except Exception as exc:
            r=dict(status='QUALITY_OR_DIAGNOSTIC_FAILED',error_type=type(exc).__name__,reason=str(exc));save(folder/'failure.json',r)
        results[date]=r;print(date,r,flush=True)
    aggregates={}
    for model in ['C0','S06B']:
        selected=all_events if model=='C0' else [e for e in all_events if e['candidate']]
        for cost in ['base','stress']:
            complete=[e['conditions'][cost] for e in selected if e['conditions'][cost]['status']=='COMPLETE_CONDITIONAL_EVENT']
            aggregates[model+'_'+cost]=dict(opportunities=len(selected),statuses=dict(Counter(e['conditions'][cost]['status'] for e in selected)),
                complete_events=len(complete),price_pnl=str(sum((D(e['price_pnl']) for e in complete),D(0))),
                fees=str(sum((D(e['fees']) for e in complete),D(0))),net_complete_only=str(sum((D(e['net']) for e in complete),D(0))),
                unresolved_exits=sum(e['conditions'][cost]['status']=='EXIT_UNRESOLVED' for e in selected))
    summary=dict(status='BOUNDED_EVENT_DIAGNOSTIC_COMPLETE_NOT_ADOPTION',intervals=results,aggregates=aggregates,
        public_requests=8,compressed_bytes=total_compressed,decoded_bytes=total_decoded,
        failed_intervals=sum(r['status']!='COMPLETE_SCOPED_EVENT_DIAGNOSTIC' for r in results.values()),
        representative_sample=False,performance_confirmation=False,account_return_computed=False,actual_orders=0,strategy_adopted=False,combined=False)
    save(out/'summary.json',summary);(out/'all_events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in all_events))
    check(sources);check(protected)
    save(out/'verification.json',dict(status='PASS_REGISTERED_DIAGNOSTIC_WITH_FAILURES_RETAINED',source_hashes_unchanged=len(sources),protected_hashes_unchanged=len(protected),tests=test.testsRun,
        artifacts={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()}))
    print(json.dumps(aggregates,indent=2),flush=True)


if __name__=='__main__':main()
