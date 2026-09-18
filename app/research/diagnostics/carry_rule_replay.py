"""Conditional hourly price proxies through the frozen E027 coordinator."""
from datetime import datetime, timezone
from decimal import Decimal as D
import heapq
import json
from pathlib import Path
import sqlite3

from tests.test_carry_pair import PairFixture

HOUR = 3_600_000


def iso(t):
    return datetime.fromtimestamp(t/1000, timezone.utc).isoformat()


def ctx(row, t, slip, *, closing=False):
    suffix = 'close' if closing else 'open'
    return dict(now_ms=t, observed_ms=t, funding_confirmed=True,
        spot_bid=str(D(str(row['spot_'+suffix]))*(1-slip)),
        spot_ask=str(D(str(row['spot_'+suffix]))*(1+slip)),
        future_bid=str(D(str(row['future_'+suffix]))*(1-slip)),
        future_ask=str(D(str(row['future_'+suffix]))*(1+slip)),
        mark=str(row['mark_'+suffix]))


def run(folder, rows, funding, *, slip_bps, extra_funding_bps, monthly_cost):
    folder = Path(folder); folder.mkdir()
    f = PairFixture(folder); slip=D(str(slip_bps))/10000
    extra=D(str(extra_funding_bps))/10000
    adjustments=[]; observations=[]; decisions=[]; deferred=[]
    by_hour={}
    for event in funding:
        if rows[0]['time_ms'] <= event['time_ms'] < rows[-1]['time_ms']+HOUR:
            by_hour.setdefault(event['time_ms']//HOUR, []).append(event)
    first_exit=None; opened_at=None
    try:
        for i,row in enumerate(rows):
            start=row['time_ms']; end=start+HOUR
            heap=[]; scheduled=set()
            def schedule(t, kind, value=None):
                key=(t,kind,str(value))
                if key not in scheduled:
                    scheduled.add(key)
                    heapq.heappush(heap,(t, {'funding':0,'cost':1,'end':2,'fill':3,'step':4}[kind],kind,str(value),value))
            schedule(start,'step')
            for event in by_hour.get(start//HOUR,[]):schedule(event['time_ms'],'funding',event)
            month=iso(start)[:7]
            if iso(end)[:7]!=month and monthly_cost:
                schedule(start,'cost',dict(id=month,amount=str(monthly_cost)))
            if i==len(rows)-1:schedule(start,'end')
            while heap:
                t,_,kind,_,value=heapq.heappop(heap)
                if t>=end:raise ValueError('synthetic order path crosses next hourly observation')
                c=ctx(row,t,slip)
                if kind=='cost':
                    f.pair.operating_cost(value['id'],value['amount'])
                    adjustments.append(dict(type='cost',posted_ms=t,**value))
                    continue
                if kind=='end':
                    if first_exit is None:first_exit=dict(time_ms=t,reason='REGISTERED_END')
                    f.pair.request_exit('registered_end');continue
                if kind=='funding':
                    deferred.append(value)
                if kind=='fill':
                    o=next(o for o in f.pair.state()['orders'] if o['id']==value)
                    price=D(c[o['market']+('_ask' if o['side']==1 else '_bid')])
                    q=D(o['qty']);fee=q*price*(D('.001') if o['market']=='spot' else D('.00025'))
                    f.publish(o['id'],qty=str(q),price=str(price),fee_usdc=str(fee),time_ms=t)
                    schedule(t+1,'step');continue
                action=f.pair.next(c)
                applied=False
                for event in list(deferred):
                    try:
                        result=f.pair.funding(str(event['time_ms']),event['time_ms'],event['mark'],str(D(str(event['rate']))-extra))
                    except ValueError as exc:
                        if str(exc)!='funding position unresolved':raise
                        continue
                    adjustments.append(dict(type='funding',posted_ms=t,time_ms=event['time_ms'],
                        mark=str(event['mark']),historical_rate=str(event['rate']),extra=str(extra),
                        effective_rate=str(D(str(event['rate']))-extra),receipt=result['receipt']))
                    deferred.remove(event);applied=True
                if applied:action=f.pair.next(c)
                state=f.pair.state()
                if state['requested_exit'] and first_exit is None:
                    first_exit=dict(time_ms=t,reason='RISK_OR_ENTRY_FAILURE',action=action['kind'],
                        spot_qty=state['spot_qty'],future_qty=state['future_qty'],
                        equity=str(f.pair.valuation(state,c)[0]))
                if action['kind']=='OPEN' and opened_at is None:opened_at=t
                if action['kind'] in ('SUBMIT','CANCEL','QUERY'):
                    result=f.pair.dispatch(action,f.paper,c)
                    decisions.append(dict(time_ms=t,action=action,result=result))
                    if result!='OBSERVED':raise ValueError('unexpected synthetic transport outcome: '+result)
                    o=next(o for o in f.pair.state()['orders'] if o['id']==action['order_id'])
                    if action['kind']=='SUBMIT' and o['kind']=='MARKET':schedule(t+1,'fill',o['id'])
                    else:schedule(t+1,'step')
                elif action['kind']=='WAIT_ORDER':
                    o=next(o for o in state['orders'] if o['id']==action['order_id'])
                    schedule(max(t+1,o['deadline_ms']),'step')
                elif action['kind'] in ('ABORT_ENTRY','LOCAL_UNSENT_CANCELED'):
                    schedule(t+1,'step')
                elif action['kind']=='ENTRY_REJECTED' and state['requested_exit']:
                    schedule(t+1,'step')
                elif action['kind']=='RECONCILIATION_REQUIRED':
                    raise ValueError('reconciliation required: '+str(state['fault']))
            state=f.pair.state();close=ctx(row,end-1,slip,closing=True)
            equity,margin=f.pair.valuation(state,close)
            reserve_fees=D(state['spot_qty'])*D(close['spot_bid'])*D('.001')+abs(D(state['future_qty']))*D(close['future_ask'])*D('.00025')
            observations.append(dict(time_ms=end-1,hour=iso(start),
                **{k:state[k] for k in ('spot_cash','future_cash','spot_qty','future_qty','future_average')},
                equity=str(equity),closeout_equity=str(equity-reserve_fees),future_margin=str(margin),phase=state['phase']))
        if deferred:raise ValueError('unresolved funding at end')
        state=f.pair.state()
        with (folder/'coordinator_audit.jsonl').open('x') as stream:
            for record in f.pair.db.execute('SELECT id,kind,payload FROM audit ORDER BY id'):
                stream.write(json.dumps(dict(id=record['id'],kind=record['kind'],payload=json.loads(record['payload'])))+'\n')
        result=dict(rows=observations,adjustments=adjustments,decisions=decisions,
            final_state=state,first_exit=first_exit,opened_at=opened_at)
        for name in ('rows','adjustments','decisions'):
            with (folder/(name+'.jsonl')).open('x') as stream:
                for record in result[name]:stream.write(json.dumps(record)+'\n')
        (folder/'final_state.json').write_text(json.dumps(state,indent=2)+'\n')
        return result
    finally:f.close()


def independent_audit(folder, rows, result, slip_bps):
    """Independent exchange-receipt book reconstruction at every hour close."""
    with sqlite3.connect(Path(folder)/'exchange.sqlite') as db:
        orders=[(json.loads(o),json.loads(r)) for o,r in db.execute('SELECT payload,receipt FROM orders')]
        sends=list(db.execute('SELECT kind,id FROM sends'))
    fills=[]
    for order,receipt in orders:
        for fill in receipt['fills']:
            fills.append(dict(**fill,market=order['market'],side=order['side'],type='fill',posted_ms=fill['time_ms']))
    timeline=sorted(fills+result['adjustments'],key=lambda e:(e['posted_ms'],e['type']=='fill'))
    sc,fc,sq,short,basis=D(500),D(500),D(0),D(0),D(0)
    slip=D(str(slip_bps))/10000;cursor=0;fund_total=D(0);historical=D(0);fund_extra=D(0);fees=D(0);costs=D(0)
    checks=0
    for row,actual in zip(rows,result['rows'],strict=True):
        while cursor<len(timeline) and timeline[cursor]['posted_ms']<=actual['time_ms']:
            e=timeline[cursor];cursor+=1
            if e['type']=='cost':sc-=D(e['amount']);costs+=D(e['amount']);continue
            if e['type']=='funding':
                q=-sum((D(f['qty'])*f['side'] for f in fills if f['market']=='future' and f['time_ms']<e['time_ms']),D(0))
                amount=q*D(e['mark'])*D(e['effective_rate'])
                if amount!=D(e['receipt']):raise ValueError('funding receipt mismatch')
                historical+=q*D(e['mark'])*D(e['historical_rate']);fund_extra+=q*D(e['mark'])*D(e['extra'])
                fc+=amount;fund_total+=amount;continue
            q,v,fee=D(e['qty']),D(e['quote']),D(e['fee_usdc']);fees+=fee
            if e['market']=='spot':sc-=e['side']*v+fee;sq+=e['side']*q-D(e['fee_btc'])
            elif e['side']==-1:short+=q;basis+=v;fc-=fee
            else:
                released=basis*q/short;fc+=released-v-fee;short-=q;basis-=released
        sb=D(str(row['spot_close']))*(1-slip);fa=D(str(row['future_close']))*(1+slip)
        equity=sc+sq*sb+fc+basis-short*fa
        expected=dict(spot_cash=sc,future_cash=fc,spot_qty=sq,future_qty=-short,
            future_average=basis/short if short else D(0),equity=equity,
            closeout_equity=equity-sq*sb*D('.001')-short*fa*D('.00025'),
            future_margin=fc+basis-short*D(str(row['mark_close'])))
        for key,v in expected.items():
            if abs(D(actual[key])-v)>D('.000000001'):raise ValueError('independent mismatch: '+key)
            checks+=1
    for kind in ('submit','cancel'):
        ids=[identity for k,identity in sends if k==kind]
        if len(ids)!=len(set(ids)):raise ValueError('duplicate external send')
    final=result['final_state']
    if sq or short:raise ValueError('conditional full-fill scenario left inventory')
    price_pnl=sc+fc-D(1000)-fund_total+fees+costs
    return dict(status='PASS_INDEPENDENT_ALL_HOURS',hours=len(rows),balance_checks=checks,
        fills=len(fills),orders=len(orders),funding_events=len(result['adjustments'])-sum(e['type']=='cost' for e in result['adjustments']),
        historical_funding=str(historical),additional_funding_paid=str(fund_extra),funding_net=str(fund_total),
        trading_fees=str(fees),operating_cost=str(costs),execution_price_pnl=str(price_pnl),
        terminal_equity=str(sc+fc),net_usdc=str(sc+fc-1000),residual_spot=str(sq),residual_future=str(-short))
