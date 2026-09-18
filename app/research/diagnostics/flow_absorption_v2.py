"""E032 second-snapshot repair; original frozen diagnostic remains unchanged."""
from collections import deque
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import json
from pathlib import Path

from app.research.data.local_order_book import LocalOrderBook

NS=10**9


def signal(point, past, trades):
    if not point['valid'] or not past['valid']: return 0,False
    selected=[x for x in trades if point['time_ns']-5*NS < x['time_ns'] <= point['time_ns']]
    if len({x['id'] for x in selected})<3: return 0,False
    buy=sum((D(x['price'])*D(x['qty']) for x in selected if not x['buyer_maker']),D(0))
    sell=sum((D(x['price'])*D(x['qty']) for x in selected if x['buyer_maker']),D(0))
    total=buy+sell
    if not total: return 0,False
    mid,old=D(point['mid']),D(past['mid'])
    direction=1 if sell/total>=D('.8') and mid>=old else -1 if buy/total>=D('.8') and mid<=old else 0
    bid=sum((D(p)*D(q) for p,q in point['bids']),D(0))
    ask=sum((D(p)*D(q) for p,q in point['asks']),D(0))
    supported=(direction==1 and bid>=ask) or (direction==-1 and ask>=bid)
    return direction,supported


def market_leg(point, side, slip_bps, qty=D('.001')):
    if not point['valid']: return dict(status='UNAVAILABLE')
    levels=point['asks'] if side==1 else point['bids']
    remaining=qty;quote=D(0);fills=[]
    for price,quantity in levels:
        take=min(remaining,D(quantity))
        if not take: continue
        raw=D(price)*(1+D(side)*D(slip_bps)/10000)
        price=(raw/D('.1')).to_integral_value(rounding=ROUND_CEILING if side==1 else ROUND_FLOOR)*D('.1')
        quote+=price*take;fills.append(dict(price=str(price),qty=str(take)))
        remaining-=take
        if not remaining: break
    if remaining: return dict(status='INSUFFICIENT_VISIBLE_SIZE',residual=str(remaining),displayed_fills=fills)
    return dict(status='COMPLETE_PROXY',quote=str(quote),fee=str(quote*D('.00025')),fills=fills)


def events(grid):
    by_time={p['time_ns']:p for p in grid};next_allowed=0;output=[]
    for p in grid:
        t=p['time_ns']
        if t<next_allowed or t+63*NS not in by_time or t-5*NS not in by_time: continue
        direction,supported=signal(p,by_time[t-5*NS],p['trades'])
        if not direction:continue
        next_allowed=t+73*NS
        event=dict(signal_ns=t,direction=direction,candidate=supported,entry_ns=t+3*NS,exit_ns=t+63*NS,conditions={})
        for name,slip in [('base',2),('stress',5)]:
            entry=market_leg(by_time[t+3*NS],direction,slip)
            if entry['status']!='COMPLETE_PROXY':
                event['conditions'][name]=dict(status='ENTRY_'+entry['status'],entry=entry);continue
            if not D('50')<=D(entry['quote'])<=D('200'):
                event['conditions'][name]=dict(status='ENTRY_NOTIONAL_REJECTED',entry=entry);continue
            close=market_leg(by_time[t+63*NS],-direction,slip)
            if close['status']!='COMPLETE_PROXY':
                event['conditions'][name]=dict(status='EXIT_UNRESOLVED',entry=entry,exit=close);continue
            price_pnl=D(direction)*(D(close['quote'])-D(entry['quote']))
            fee=D(entry['fee'])+D(close['fee'])
            event['conditions'][name]=dict(status='COMPLETE_CONDITIONAL_EVENT',entry=entry,exit=close,
                price_pnl=str(price_pnl),fees=str(fee),net=str(price_pnl-fee))
        output.append(event)
    return output


def grid_from_raw(path, start_ns, end_ns, timestamp_parser):
    """One source interval. All decisions use only rows received by their grid time."""
    rows=[];last_time=start_ns;counts={}
    for line in Path(path).read_text().splitlines():
        if not line.strip(): rows.append((last_time,None));continue
        stamp,payload=line.split(' ',1);t=timestamp_parser(stamp)
        if not start_ns<=t<end_ns or t<last_time:raise ValueError('raw time range/order')
        m=json.loads(payload)
        if not m['stream'].startswith('btcusdc@') or m['data'].get('s','BTCUSDC')!='BTCUSDC':raise ValueError('wrong symbol')
        rows.append((t,m));last_time=t
        key=m['data'].get('e','depthSnapshot');counts[key]=counts.get(key,0)+1
    book=LocalOrderBook();book.begin_session('0',started_ns=start_ns)
    current=0;generation=0;last_depth=last_mark=None;reset=start_ns;seen={};previous_trade=None
    trades=deque();grid=[];snapshots=0;gaps=0;depth_changes=0;depth_history=deque(maxlen=4096)
    mark_identity=None
    for t in range(start_ns,end_ns,NS):
        while current<len(rows) and rows[current][0]<=t:
            received,message=rows[current];current+=1
            if message is None:
                generation+=1;book=LocalOrderBook();book.begin_session(str(generation),started_ns=received)
                last_depth=last_mark=None;reset=received;trades.clear();depth_history.clear();gaps+=1;continue
            d=message['data'];kind=d.get('e')
            if message['stream'].endswith('@depthSnapshot'):
                if message.get('generated') is not True: raise ValueError('snapshot provenance')
                if snapshots and book.state!='BUFFERING':
                    # The supplier snapshot can arrive after its covering update.
                    # Only replay already received history, never backdate publication.
                    history=list(depth_history);identity=d['lastUpdateId']
                    covering=next((i for i,(_,old) in enumerate(history) if old['U']<=identity<=old['u']),None)
                    replay=history[covering:] if covering is not None else []
                    generation+=1;book=LocalOrderBook();book.begin_session(str(generation),started_ns=replay[0][0] if replay else received)
                    for when,old in replay:book.ingest(old,session=book.session,received_ns=when)
                book.install_snapshot(d,session=book.session,available_ns=received)
                reset=received;snapshots+=1
            elif kind=='depthUpdate':
                depth_history.append((received,d))
                if last_depth is not None and received-last_depth>NS:reset=received
                outcome=book.ingest(d,session=book.session,received_ns=received)
                if outcome!='DUPLICATE':last_depth=received;depth_changes+=1
            elif kind=='markPriceUpdate':
                identity=(d['E'],d['T'],d['p'],d['i'],d['r'])
                if identity==mark_identity: continue
                if mark_identity and identity[0]<=mark_identity[0]:raise ValueError('mark order/conflict')
                if last_mark is None or received-last_mark>3*NS:reset=received
                last_mark=received;mark_identity=identity
            elif kind=='aggTrade':
                identity=d['a'];canonical=tuple(d.get(k) for k in ('a','p','q','f','l','T','m'))
                if identity in seen:
                    if seen[identity]!=canonical:raise ValueError('trade ID conflict')
                    continue
                if previous_trade is not None and identity!=previous_trade+1:raise ValueError('trade ID order/gap unverified')
                if type(d['m']) is not bool or D(d['p'])<=0 or D(d['q'])<=0 or d['f']>d['l']:raise ValueError('trade fields')
                seen[identity]=canonical;previous_trade=identity
                trades.append(dict(id=identity,time_ns=received,price=d['p'],qty=d['q'],buyer_maker=d['m']))
            if book.state=='INVALID': raise ValueError('invalid L2 '+str(book.reason))
        while trades and trades[0]['time_ns']<=t-5*NS: trades.popleft()
        fresh=(book.state=='LIVE' and last_depth is not None and t-last_depth<=NS and last_mark is not None and t-last_mark<=3*NS)
        if not fresh:reset=t
        ready=fresh and t-reset>=60*NS
        if fresh:
            bids=sorted(book.bids.items(),reverse=True)[:5];asks=sorted(book.asks.items())[:5]
            # Top five must stay inside the initial known price range.
            ready=ready and len(bids)==5 and len(asks)==5 and bids[-1][0]>=book.bid_floor and asks[-1][0]<=book.ask_ceiling
            mid=(bids[0][0]+asks[0][0])/2
        else:bids=[];asks=[];mid=D(0)
        grid.append(dict(time_ns=t,valid=bool(ready),mid=str(mid),
            bids=[[str(p),str(q)] for p,q in bids],asks=[[str(p),str(q)] for p,q in asks],trades=list(trades),
            last_depth_ns=last_depth,last_mark_ns=last_mark,quality_reset_ns=reset))
    # No decisions are generated from the sub-second tail after the final grid.
    if not snapshots: raise ValueError('missing snapshot')
    return grid,dict(raw_rows=len(rows),counts=counts,grid_points=len(grid),valid_points=sum(p['valid'] for p in grid),
        snapshots=snapshots,disconnect_markers=gaps,unique_trade_ids=len(seen),
        trailing_records_after_last_grid=len(rows)-current,last_decision_ns=grid[-1]['time_ns'],
        tail_scope='Raw time/symbol parsed, state transitions after last grid not evaluated; no decisions there')
