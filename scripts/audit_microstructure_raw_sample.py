"""Post-access schema and independent L2 audit for the fixed E031 raw sample."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from fractions import Fraction as F
from pathlib import Path
import calendar
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.local_order_book import LocalOrderBook
from scripts.audit_microstructure_fitness import check, load, lines, save, sha, trade_profile


def timestamp_ns(text):
    if not text.endswith('Z'): raise ValueError('UTC Z required')
    whole, fraction=text[:-1].split('.') if '.' in text else (text[:-1],'')
    if len(fraction)>9 or (fraction and not fraction.isdigit()): raise ValueError('timestamp precision')
    return calendar.timegm(datetime.strptime(whole,'%Y-%m-%dT%H:%M:%S').timetuple())*10**9+int(fraction.ljust(9,'0') or 0)


def main():
    base=ROOT/'reports/validation/e031_raw_sample_access_20260919'
    proof=load(base/'verification.json'); check(proof['artifacts'],base)
    if load(base/'result.json')['status']!='COMPLETE_RESPONSE_PENDING_SCHEMA_AND_REPLAY': raise ValueError('access not complete')
    out=ROOT/'reports/validation/e031_raw_sample_audit_20260919';out.mkdir(exist_ok=False)
    sources={n:sha(ROOT/n) for n in ['scripts/audit_microstructure_raw_sample.py','app/research/data/local_order_book.py','scripts/audit_microstructure_fitness.py']}
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),classification='POST_ACCESS_SCHEMA_REPLAY_NO_SIGNAL_OR_PNL',source_hashes=sources,
        input_hashes={str(p.relative_to(ROOT)):sha(p) for p in base.iterdir() if p.is_file()},
        checks=['UTC nanosecond precision/order/range','snapshot receipt not exchange timestamp','pu chain and independent Fraction book','exact-u ticker overlap','aggregate identifiers'],
        statistical_evaluation=False,additional_requests=0))
    # Preserve seven fractional digits; a float/microsecond parse loses this boundary.
    assert timestamp_ns('2024-09-01T00:00:00.0000001Z')-timestamp_ns('2024-09-01T00:00:00Z')==100
    start=timestamp_ns('2024-09-01T00:00:00Z');end=start+300*10**9
    records=[];disconnects=0;prior=start
    for number,line in enumerate((base/'raw.ndjson').read_text().splitlines(),1):
        if not line.strip(): disconnects+=1;continue
        local,wire=line.split(' ',1);t=timestamp_ns(local);message=json.loads(wire)
        if not start<=t<end or t<prior: raise ValueError('source timestamp range/order')
        if not message['stream'].startswith('btcusdc@'): raise ValueError('wrong stream')
        if message['data'].get('s','BTCUSDC')!='BTCUSDC': raise ValueError('wrong symbol')
        records.append(dict(line=number,time_ns=t,local_timestamp=local,message=message));prior=t
    snapshots=[r for r in records if r['message']['stream'].endswith('@depthSnapshot')]
    if len(snapshots)!=1 or disconnects:
        save(out/'failure.json',dict(reason='Current scoped replayer requires one snapshot/no disconnect; preserve unhandled boundaries',snapshot_count=len(snapshots),disconnects=disconnects))
        raise ValueError('scoped format requires further boundary handling')
    snapshot_record=snapshots[0];snapshot=snapshot_record['message']['data']
    if snapshot_record['message'].get('generated') is not True: raise ValueError('snapshot provenance flag')
    tickers=defaultdict(list)
    for r in records:
        d=r['message']['data']
        if d.get('e')=='bookTicker': tickers[d['u']].append(d)
    book=LocalOrderBook();book.begin_session('tardis-fixed-sample',started_ns=start)
    rb,ra,last=None,None,None;pending=[];quotes=[];checked=0;matched=0;depth_count=0;reference_applied=0;pre_snapshot=0
    def reference_apply(d):
        nonlocal last,reference_applied,pre_snapshot
        if d['u']<snapshot['lastUpdateId']:
            pre_snapshot+=1;return
        if last is None:
            if not d['U']<=snapshot['lastUpdateId']<=d['u']: raise ValueError('independent bridge')
        elif d['pu']!=last or d['u']<=last: raise ValueError('independent chain')
        for key,side in [('b',rb),('a',ra)]:
            for p,q in d[key]:
                p,q=F(p),F(q)
                if p<=0 or q<0: raise ValueError('nonpositive price/negative size')
                if q==0: side.pop(p,None)
                else: side[p]=q
        last=d['u'];reference_applied+=1
    for r in records:
        d=r['message']['data'];stream=r['message']['stream'];t=r['time_ns']
        if stream.endswith('@depthSnapshot'):
            rb={F(p):F(q) for p,q in snapshot['bids']};ra={F(p):F(q) for p,q in snapshot['asks']}
            for old in pending: reference_apply(old)
            book.install_snapshot(snapshot,session=book.session,available_ns=t)
        elif d.get('e')=='depthUpdate':
            depth_count+=1
            if rb is None: pending.append(d)
            else: reference_apply(d)
            book.ingest(d,session=book.session,received_ns=t)
        else: continue
        if book.state=='INVALID': raise ValueError('engine invalid: '+str(book.reason))
        if book.state!='LIVE': continue
        if book.last_u!=last or {F(p):F(q) for p,q in book.bids.items()}!=rb or {F(p):F(q) for p,q in book.asks.items()}!=ra:
            raise ValueError('independent full book mismatch')
        checked+=1;q=book.quote(now_ns=t)
        if q['available_ns']<snapshot_record['time_ns']: raise ValueError('snapshot backdating')
        for ticker in tickers.get(q['u'],[]):
            if [F(ticker[k]) for k in ('b','B','a','A')]!=[F(q[k]) for k in ('bid','bid_quantity','ask','ask_quantity')]:
                raise ValueError('exact-u quote mismatch')
            matched+=1
        quotes.append(dict(**q,source_line=r['line'],source_local_timestamp=r['local_timestamp']))
    if not quotes: raise ValueError('no usable book')
    trades=[dict(data=r['message']['data'],available_ns=r['time_ns']) for r in records if r['message']['data'].get('e')=='aggTrade']
    for r in trades:
        d=r['data']
        if F(d['p'])<=0 or F(d['q'])<=0 or type(d['m']) is not bool or d['f']>d['l']: raise ValueError('trade schema')
    counts=Counter(r['message']['data'].get('e','depthSnapshot') for r in records)
    durations=[b['available_ns']-a['available_ns'] for a,b in zip(quotes,quotes[1:])]
    summary=dict(status='PASS_SCOPED_ARCHIVED_L2_SCHEMA_REPLAY',source_rows=len(records),counts=dict(counts),
        first_local=records[0]['local_timestamp'],last_local=records[-1]['local_timestamp'],
        observed_receive_span_seconds=(records[-1]['time_ns']-records[0]['time_ns'])/1e9,
        snapshot_received=snapshot_record['local_timestamp'],snapshot_exchange_T_ms=snapshot['T'],
        snapshot_levels=[len(snapshot['bids']),len(snapshot['asks'])],snapshot_is_supplier_REST_generated=True,
        received_snapshot_age_vs_exchange_T_ms=(snapshot_record['time_ns']-snapshot['T']*10**6)/1e6,
        depth_events=depth_count,reference_applied_depth_updates=reference_applied,pre_snapshot_updates_discarded=pre_snapshot,
        full_book_comparisons=checked,exact_update_ticker_matches=matched,ticker_mismatches=0,
        first_publish=quotes[0]['source_local_timestamp'],last_publish=quotes[-1]['source_local_timestamp'],
        publish_span_seconds=(quotes[-1]['available_ns']-quotes[0]['available_ns'])/1e9,
        max_publish_gap_ms=max(durations)/1e6,disconnect_markers=disconnects,trade_profile=trade_profile(trades),
        source_clock='Supplier local capture time; not this host receive/commit/order latency',
        historical_snapshot_top1000_only=True,full_market_depth_known=False,maker_fill_calibrated=False,
        new_market_requests=0,actual_orders=0,strategy_runs=0,profitability_evidence=False)
    save(out/'summary.json',summary)
    (out/'quotes.jsonl').write_text(''.join(json.dumps(q)+'\n' for q in quotes))
    save(out/'final_book.json',book.checkpoint())
    check(sources);check(proof['artifacts'],base)
    save(out/'verification.json',dict(status='PASS_SOURCE_SCHEMA_AND_INDEPENDENT_FRACTION_REPLAY',source_hashes=sources,
        input_verification_sha256=sha(base/'verification.json'),artifacts={p.name:sha(p) for p in out.iterdir() if p.is_file()}))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
