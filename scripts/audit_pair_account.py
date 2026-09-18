"""Independent arithmetic over immutable conditional fills and funding inputs."""
from collections import defaultdict
from decimal import Decimal as D,ROUND_CEILING,ROUND_FLOOR
import math


def verify_signals(rows,values):
    logs=[math.log(float(r['eth_close'])/float(r['btc_close'])) for r in rows]
    count=0
    for i in range(len(rows)):
        if i<720:
            if values[i] is not None:raise ValueError('signal before warmup')
            continue
        prior=logs[i-720:i];mu=math.fsum(prior)/720
        sd=math.sqrt(math.fsum((x-mu)**2 for x in prior)/720)
        expected=(logs[i]-mu)/sd if sd>1e-12 else None
        if expected is None:
            if values[i] is not None:raise ValueError('zero variance signal')
        elif values[i] is None or abs(values[i]-expected)>1e-6:raise ValueError('independent z score')
        count+=1
    return dict(status='PASS_PRIOR_720_SCALAR_MOMENTS',values=count,initial_unavailable=720)


def verify(rows,funding,result,config):
    source={(e['leg'],e['time_ms']):e for e in funding}
    prices={r['time_ms']:r for r in rows};ticks=dict(btc=D('.1'),eth=D('.01'))
    slip=D(str(config['slip_bps']))/10000;extra=D(str(config['extra_funding_bps']))/10000
    cash=dict(btc=D(400),eth=D(400));positions=dict(btc=D(0),eth=D(0));basis=dict(btc=D(0),eth=D(0))
    outside=D(200);cycle_net=defaultdict(lambda:D(0));seen=set();cursor=0;checked=0
    totals={k:D(0) for k in ('price_pnl','historical_funding','extra_funding','fees','operating_cost')}
    ledger=result['ledger']
    def tick_price(row,leg,side,closing=False):
        p=D(str(row[leg+('_close' if closing else '_open')]))*(1+side*slip)
        return (p/ticks[leg]).to_integral_value(rounding=ROUND_CEILING if side>0 else ROUND_FLOOR)*ticks[leg]
    for row,actual in zip(rows,result['hourly'],strict=True):
        while cursor<len(ledger) and ledger[cursor]['time_ms']<=actual['time_ms']:
            e=ledger[cursor];cursor+=1;kind=e['type'];identity=(kind,e['id'])
            if identity in seen:raise ValueError('duplicate ledger event')
            seen.add(identity)
            if kind=='cost':
                amount=D(str(config['monthly_cost']))
                if D(e['amount'])!=amount:raise ValueError('cost rate')
                outside-=amount;totals['operating_cost']+=amount;continue
            leg=e['leg'];q=positions[leg]
            if kind=='funding':
                orig=source[leg,e['settlement_ms']]
                hist=-q*D(str(orig['mark']))*D(str(orig['rate']))
                added=abs(q)*D(str(orig['mark']))*extra
                if D(e['qty'])!=q or D(e['amount'])!=hist-added:raise ValueError('funding ownership/timing')
                cash[leg]+=hist-added;totals['historical_funding']+=hist;totals['extra_funding']+=added
                if e['cycle_id'] is not None:cycle_net[e['cycle_id']]+=hist-added
                continue
            quantity=D(e['qty']);price=D(e['price']);side=e['side'];fee=quantity*price*D('.00025')
            expected=tick_price(prices[e['time_ms']//3600000*3600000],leg,side)
            if expected!=price or fee!=D(e['fee']) or quantity*price!=D(e['quote']):raise ValueError('conditional execution price/fee')
            signed=quantity*side;realized=D(0)
            if q and q*signed<0:
                if quantity>abs(q):raise ValueError('overclose')
                released=basis[leg]*quantity/abs(q)
                realized=side*(released-quantity*price)
                basis[leg]-=released
            else:basis[leg]+=quantity*price
            positions[leg]+=signed;cash[leg]+=realized-fee
            totals['price_pnl']+=realized;totals['fees']+=fee;cycle_net[e['cycle_id']]+=realized-fee
        equity=outside
        for leg in ('btc','eth'):
            q=positions[leg];avg=basis[leg]/abs(q) if q else D(0)
            exit_price=tick_price(row,leg,-1 if q>0 else 1,True)
            equity+=cash[leg]+q*(exit_price-avg)-abs(q)*exit_price*D('.00025')
            margin=cash[leg]+q*(D(str(row[leg+'_mark_close']))-avg)
            for key,expected in [('wallet',cash[leg]),('position',q),('average',avg),('margin',margin)]:
                if abs(D(actual[key][leg])-expected)>D('.000000001'):raise ValueError('hourly '+key)
                checked+=1
        if abs(equity-D(actual['equity']))>D('.000000001') or outside!=D(actual['outside']):raise ValueError('hourly total')
        checked+=2
    for cycle in result['cycles']:
        if abs(cycle_net[cycle['id']]-D(cycle['net_pnl']))>D('.000000001'):raise ValueError('cycle net mismatch')
    terminal=outside+sum(cash.values())
    identity=1000+totals['price_pnl']+totals['historical_funding']-totals['extra_funding']-totals['fees']-totals['operating_cost']
    if any(positions.values()) or abs(terminal-identity)>D('.000000001'):raise ValueError('terminal accounting identity')
    if totals['operating_cost']!=24*D(str(config['monthly_cost'])):raise ValueError('cost coverage')
    return dict(status='PASS_ALL_HOURS_AND_CYCLES',hourly_checks=checked,hours=len(rows),
        ledger_events=len(ledger),cycles=len(result['cycles']),terminal_equity=str(terminal),
        net_usdc=str(terminal-1000),**{k:str(v) for k,v in totals.items()})
