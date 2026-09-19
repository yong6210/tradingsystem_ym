"""Bounded public-feed paper probe. GET-only, no credentials or order transport.

Warmup reconstructs indicator history without decisions. All seeded zone states
are discarded and re-registered at actual retrieval time before live decisions.
Fills are an explicit displayed-depth simulation, not exchange queue evidence.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.market_adapter_v02 import MarketAdapterV02 as MarketAdapter
from app.research.recovery.models import Bar,Quote,dec,jsonable,floor_step
from app.research.recovery.zone_observer import ZoneObserver

ALLOWED={'time','klines','ticker/bookTicker','premiumIndex'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default='configs/research/recovery_market_v02.json')
    p.add_argument('--seconds',type=int,default=120);p.add_argument('--output',required=True)
    args=p.parse_args()
    if not 1<=args.seconds<=600:raise ValueError('bounded probe requires 1..600 seconds')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    config=json.loads(Path(args.config).read_text());a=MarketAdapter(config)
    raw_stream=(out/'public_responses.jsonl').open('w')
    metrics=[]; faults=[]; offset=0
    def get(name,**params):
        if name not in ALLOWED:raise ValueError('public GET allowlist only')
        url='https://fapi.binance.com/fapi/v1/'+name+'?'+urllib.parse.urlencode(params)
        before=time.time_ns()//1000000
        with urllib.request.urlopen(url,timeout=10) as response:raw=response.read()
        after=time.time_ns()//1000000;value=json.loads(raw)
        raw_stream.write(json.dumps(dict(url=url,request_ms=before,received_ms=after,body=value))+'\n');raw_stream.flush()
        metrics.append(dict(endpoint=name,request_ms=before,received_ms=after,round_trip_ms=after-before))
        return value,after
    def now():return time.time_ns()//1000000+offset
    try:
        clock,received=get('time');offset=int(clock['serverTime'])-received
        boundary=now()//60000*60000
        candles,_=get('klines',symbol='BTCUSDC',interval='1m',startTime=boundary-1440*60000,endTime=boundary-1,limit=1500)
        if [int(x[0]) for x in candles]!=list(range(boundary-1440*60000,boundary,60000)):
            raise ValueError('incomplete bootstrap history')
        for row in candles:
            end=int(row[0])+60000
            a.observe(Bar(end,row[1],row[2],row[3],row[4],end))
        registered=now()
        a.zones={k:ZoneObserver.start(replace(o.history.zone,available_ms=registered),o.side,o.buffer,
                                      'public live probe; historical candidate re-registered now',registered)
                 for k,o in a.zones.items()}
        # Indicator history is retained; prior zone validation never authorizes entry.
        premium,_=get('premiumIndex',symbol='BTCUSDC')
        funding_boundary=int(premium['nextFundingTime'])
        started=time.monotonic(); live_bars=0; quotes=0
        while time.monotonic()-started<args.seconds:
            try:
                latest,received=get('klines',symbol='BTCUSDC',interval='1m',startTime=a.last_end,limit=10)
                receipt=received+offset
                for row in latest:
                    end=int(row[0])+60000
                    if a.last_end<end<=receipt:
                        a.observe(Bar(end,row[1],row[2],row[3],row[4],receipt));live_bars+=1
                book,received=get('ticker/bookTicker',symbol='BTCUSDC');receipt=received+offset
                e=a.replay.engine
                if receipt>=funding_boundary:
                    a.emit(dict(type='fault',time_ms=receipt,reason='funding_reconciliation_required'))
                bid,ask=dec(book['bidPrice']),dec(book['askPrice'])
                cash=e.ledger.cash if e.ledger else e.equity
                cap=max(dec(0),cash)*dec(config['simulation']['equity_exposure_fraction'])/ask
                held=e.ledger.quantity if e.ledger else dec(0)
                capacity=min(dec(book['bidQty']),dec(book['askQty']))*dec(config['simulation']['participation'])
                age=receipt-int(book['time'])
                quote=Quote(receipt,bid,ask,
                            cap,max(dec(0),cap-held),capacity,0<=age<=10000,receipt<funding_boundary)
                if not quote.execution_ok:
                    a.emit(dict(type='fault',time_ms=receipt,reason='stale_public_quote'))
                # An uncertain quote must not fabricate even a risk-reducing fill.
                a.decide(quote,simulate_fills=quote.execution_ok);quotes+=1
                metrics[-1]['book_age_ms']=age
            except Exception as exc:
                faults.append(str(exc))
                a.emit(dict(type='fault',time_ms=max(now(),a.replay.engine.last_time),reason='public_feed_fault',connected=False))
                break # no silent resume after an uncertain feed or partially applied event
            time.sleep(min(3,max(0,args.seconds-(time.monotonic()-started))))
        checkpoint=a.checkpoint()
        restored=MarketAdapter.restore(config,checkpoint,max(now(),a.replay.engine.last_time)+1)
        (out/'checkpoint.json').write_text(json.dumps(checkpoint)+'\n')
        fills=[r for ledger in [*a.replay.engine.archived_ledgers.values(),*([a.replay.engine.ledger] if a.replay.engine.ledger else [])]
               for r in ledger.rows if r['type']=='fill']
        summary=dict(status='PASS' if not faults else 'FAULT_LOCKED',scope='bounded public-feed paper smoke, not operational certification',
                     requested_seconds=args.seconds,elapsed_seconds=time.monotonic()-started,live_bars=live_bars,quotes=quotes,
                     simulated_fills=len(fills),live_orders_sent=0,faults=faults,
                     restart_locked='restart' in restored.replay.engine.locks,
                     zones_restored=restored.zones==a.zones,pre_restart_locks=sorted(a.replay.engine.locks),
                     post_restart_locks=sorted(restored.replay.engine.locks),
                     partial_fill_evidence='Synthetic integration drill only unless ledger shows a partial simulated fill',
                     limits=['REST polling is not a durable websocket/order transport','No automatic reconciliation or resume',
                             'Warmup zone validity reset at actual retrieval; needs new live reactions',
                             'No live funding crossing supported: locks at next funding boundary'])
    except Exception as exc:
        summary=dict(status='BLOCKED',error=str(exc),live_orders_sent=0)
    finally:
        raw_stream.close()
    for name,value in [('summary',summary),('metrics',metrics),('snapshot',a.replay.engine.snapshot())]:
        (out/(name+'.json')).write_text(json.dumps(jsonable(value),indent=2)+'\n')
    with (out/'events.jsonl').open('w') as stream:
        for event in a.replay.events:stream.write(json.dumps(event)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
