"""Public archive replay. Candle-open quote proxies, never real executions."""
import argparse
import csv
import hashlib
import io
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.zone_reuse import MarketAdapterV03 as MarketAdapter
from app.research.recovery.models import Bar, Quote, dec, floor_step, jsonable


def stamp(value):
    return int(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()*1000)


def rows(paths):
    result = []
    for path in paths:
        raw = path.read_bytes()
        expected = path.with_name(path.name+'.CHECKSUM').read_text().split()[0]
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f'checksum mismatch: {path}')
        with ZipFile(io.BytesIO(raw)) as archive:
            for member in archive.namelist():
                result.extend(csv.DictReader(io.TextIOWrapper(archive.open(member))))
    return sorted(result,key=lambda r:int(r['open_time']))


def run(config, data, funding, start, end, output):
    a = MarketAdapter(config)
    warm = start-1440*60000
    selected = [r for r in data if warm <= int(r['open_time']) < end]
    if [int(r['open_time']) for r in selected] != list(range(warm,end,60000)):
        raise ValueError('incomplete/duplicate warmup or evaluation minutes')
    funds = sorted([r for r in funding if warm <= int(r['fundingTime']) < end],key=lambda r:int(r['fundingTime']))
    fi = 0
    for i, row in enumerate(selected[:-1]):
        t = int(row['open_time'])+60000
        while fi < len(funds) and int(funds[fi]['fundingTime']) <= t:
            f = funds[fi]; fi += 1
            e = a.replay.engine
            if e.ledger and e.ledger.quantity:
                a.emit(dict(type='funding',event_id=str(f['fundingTime']),time_ms=int(f['fundingTime']),
                            amount=e.plan.side*e.ledger.quantity*dec(f['markPrice'])*dec(f['fundingRate'])))
        a.observe(Bar(t,row['open'],row['high'],row['low'],row['close'],t))
        if t < start:
            continue
        # Funding at minute+1ms precedes the simulated execution at that instant.
        while fi < len(funds) and int(funds[fi]['fundingTime']) <= t+1:
            f = funds[fi]; fi += 1
            e = a.replay.engine
            if e.ledger and e.ledger.quantity:
                a.emit(dict(type='funding',event_id=str(f['fundingTime']),time_ms=int(f['fundingTime']),
                            amount=e.plan.side*e.ledger.quantity*dec(f['markPrice'])*dec(f['fundingRate'])))
        e = a.replay.engine
        equity = e.ledger.cash if e.ledger else e.equity
        opening = dec(selected[i+1]['open'])
        spread = dec(config['simulation']['half_spread_bps'])/10000
        bid = floor_step(opening*(1-spread),e.costs.tick)
        ask = floor_step(opening*(1+spread),e.costs.tick)+e.costs.tick
        cap = max(dec(0),equity)*dec(config['simulation']['equity_exposure_fraction'])/opening
        held = e.ledger.quantity if e.ledger else dec(0)
        quote = Quote(t+1,bid,ask,cap,max(dec(0),cap-held),dec(row['volume'])*dec(config['simulation']['participation']),True,True)
        a.decide(quote,simulate_fills=True)
    e = a.replay.engine
    ledgers = list(e.archived_ledgers.values())+([e.ledger] if e.ledger else [])
    cash = e.ledger.cash if e.ledger else e.equity
    events = [r for ledger in ledgers for r in ledger.rows]
    snapshot = e.snapshot()
    summary = dict(scope='single-account sequential synthetic candle-open fills, no live orders',
                   start_ms=start,end_exclusive_ms=end,minutes=len(selected),campaigns=len(ledgers),
                   settled_campaigns=sum(l.settled for l in ledgers),cash=cash,cash_change=cash-dec(config['controller']['initial_equity']),
                   open_quantity=e.ledger.quantity if e.ledger else 0,
                   fills=sum(r['type']=='fill' for r in events),funding_events=sum(r['type']=='funding' for r in events),
                   actions=Counter(r['action'] for r in e.trace),
                   rejection_reasons=Counter(reason for r in e.trace if r['action']=='entry_assessment'
                                             for reason in r['assessment']['reasons']),
                   order_reasons=Counter(r['reason'] for r in e.trace if r['action']=='order_intent'),
                   zone_reuse_reviews=len(a.reuse_reviews),zone_reuse_allowed=sum(r['allowed'] for r in a.reuse_reviews),zone_reuse_reasons=Counter(reason for r in a.reuse_reviews for reason in r['reasons']),live_orders_sent=0, quote_model='signal: next minute open +/- half spread; broker alone applies slippage; prior-minute volume capacity',
                   limitations=['Not observed historical orderbook or stop fills','Open position is right censored, cash is not total equity',
                                'Target reachability is excursion frequency, not probability of profitable exit'])
    output.mkdir(parents=True,exist_ok=False)
    for name,value in [('summary',summary),('snapshot',snapshot),('config',config)]:
        (output/(name+'.json')).write_text(json.dumps(jsonable(value),ensure_ascii=False,indent=2)+'\n')
    for name,values in [('events',a.replay.events),('decisions',e.trace),('ledger',events),('zone_reuse',a.reuse_reviews)]:
        with (output/(name+'.jsonl')).open('w') as stream:
            for value in values:
                stream.write(json.dumps(jsonable(value),ensure_ascii=False)+'\n')
    print(json.dumps(jsonable(summary),ensure_ascii=False),flush=True)
    return a,summary


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',default='configs/research/recovery_market_v03.json')
    p.add_argument('--archives',nargs='+',required=True)
    p.add_argument('--funding',required=True)
    p.add_argument('--start',required=True); p.add_argument('--end',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    run(json.loads(Path(args.config).read_text()),rows([Path(x) for x in args.archives]),
        json.loads(Path(args.funding).read_text()),stamp(args.start),stamp(args.end),Path(args.output))


if __name__=='__main__':
    main()
