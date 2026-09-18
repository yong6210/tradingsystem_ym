"""Fixed-ledger concentration and calendar PnL attribution, not selection."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal as D
from statistics import median

from .economics import close, dec, exit_reference, fill_components

FLOW_KEYS = ('realized', 'unrealized_change', 'fill_mtm', 'slippage', 'tick_rounding',
             'reference_mtm', 'fees', 'historical_funding', 'stress_funding', 'net')


def concentration(rows, top_counts):
    if not rows:
        raise ValueError('nonempty observations required')
    values = [dec(row['net']) for row in rows]
    winners = sorted((i for i,v in enumerate(values) if v>0), key=lambda i:(-values[i],i))
    losses = [v for v in values if v<0]
    positive = sum((values[i] for i in winners),D(0))
    negative = -sum(losses,D(0))
    net = positive-negative
    tops = []
    for count in top_counts:
        if not isinstance(count,int) or count<=0:
            raise ValueError('positive integer top count required')
        picked = winners[:count]
        amount = sum((values[i] for i in picked),D(0))
        tops.append(dict(requested_count=count, actual_count=len(picked),
                         ids=[rows[i]['id'] for i in picked], profit=float(amount),
                         positive_profit_share=float(amount/positive) if positive else None,
                         arithmetic_net_without_top=float(net-amount)))
    return dict(observations=len(rows),winning=len(winners),losing=len(losses),
                flat=sum(v==0 for v in values),net=float(net),
                positive_profit=float(positive),negative_loss=float(negative),
                win_rate=len(winners)/len(rows),median_net=float(median(values)),
                mean_winner=float(positive/len(winners)) if winners else None,
                mean_loser=float(-negative/len(losses)) if losses else None,
                profit_factor=float(positive/negative) if negative else None,top=tops)


def direction_groups(cycles):
    groups = []
    previous_exit = None
    for cycle in cycles:
        if cycle['side'] not in (-1,1) or cycle['exit_time'] < cycle['entry_time']:
            raise ValueError('invalid cycle')
        if previous_exit is not None and cycle['entry_time'] < previous_exit:
            raise ValueError('overlapping or unordered cycles')
        if not groups or cycle['side'] != groups[-1]['side']:
            groups.append(dict(id=len(groups),side=cycle['side'],entry_time=cycle['entry_time'],
                               exit_time=cycle['exit_time'],cycle_ids=[],net=D(0)))
        group=groups[-1]
        group['cycle_ids'].append(cycle['id'])
        group['net']+=dec(cycle['net'])
        group['exit_time']=cycle['exit_time']
        previous_exit=cycle['exit_time']
    return [group | dict(net=float(group['net'])) for group in groups]


def event_costs(events, trades, stops, minutes, costs):
    """Tie every observed fill to its frozen reference, preserving event order."""
    components = {}
    cycle = 0
    opened = False
    for index,event in enumerate(events):
        kind=event['kind']
        if kind=='funding':
            if not opened:
                raise ValueError('funding while flat')
            continue
        if kind not in ('entry','exit') or cycle>=len(trades):
            raise ValueError('unexpected event')
        trade=trades[cycle]
        side=trade['side'] if kind=='entry' else -trade['side']
        if event['time']!=trade[kind+'_time'] or event['side']!=side:
            raise ValueError('event/cycle identity differs')
        close(event['qty'],trade['quantity'])
        if kind=='entry':
            if opened:
                raise ValueError('entry while open')
            reference=float(minutes.o.iloc[trade['entry_minute']])
            opened=True
        else:
            if not opened:
                raise ValueError('exit while flat')
            reference=exit_reference(trade,index,stops,minutes)
            opened=False
            cycle+=1
        slip,tick=fill_components(reference,event['price'],side,event['qty'],costs)
        components[index]=dict(slippage=slip,tick_rounding=tick)
    if opened or cycle!=len(trades):
        raise ValueError('incomplete cycles')
    return components


def cycle_attribution(events, trades, components):
    rows=[]
    active=None
    for index,event in enumerate(events):
        kind=event['kind']
        if kind=='entry':
            if active is not None:
                raise ValueError('overlapping entries')
            trade=trades[len(rows)]
            active=dict(id=len(rows),side=trade['side'],entry_time=trade['entry_time'],
                        exit_time=trade['exit_time'],reason=trade['reason'],
                        **dict.fromkeys(('fill_pnl','slippage','tick_rounding','fees',
                                         'historical_funding','stress_funding'),D(0)))
        if active is None:
            raise ValueError('event while flat')
        if kind=='funding':
            active['historical_funding']+=dec(event['historical_amount'])
            active['stress_funding']+=dec(event['stress_amount'])
        elif kind in ('entry','exit'):
            active['fees']+=dec(event['fee'])
            for key,value in components[index].items():
                active[key]+=value
            if kind=='exit':
                active['fill_pnl']+=dec(event['pnl'])
                active['reference_pnl']=active['fill_pnl']+active['slippage']+active['tick_rounding']
                active['net']=active['fill_pnl']-active['fees']-active['historical_funding']-active['stress_funding']
                close(active['net'],trades[len(rows)]['net_pnl'])
                rows.append({k:float(v) if isinstance(v,D) else v for k,v in active.items()})
                active=None
        else:
            raise ValueError('unknown event')
    if active is not None or len(rows)!=len(trades):
        raise ValueError('incomplete cycles')
    return rows


def daily_attribution(events, daily, closing_prices, components, initial=1000):
    """Decimal cash/position replay with explicit mark-to-market day boundaries."""
    if not daily or initial<=0:
        raise ValueError('daily observations and positive capital required')
    by_day=defaultdict(list)
    previous_time=''
    for index,event in enumerate(events):
        if event['time']<previous_time:
            raise ValueError('unordered events')
        previous_time=event['time']
        by_day[event['time'][:10]].append((index,event))
    qty=average=previous_unrealized=D(0)
    cash=previous_equity=dec(initial)
    previous_day=date.fromisoformat(daily[0]['day'])-timedelta(days=1)
    result=[]
    for row in daily:
        day=date.fromisoformat(row['day'])
        if day!=previous_day+timedelta(days=1):
            raise ValueError('noncontinuous days')
        sums=dict.fromkeys(FLOW_KEYS,D(0))
        for index,event in by_day.pop(row['day'],[]):
            kind=event['kind']
            if kind=='entry':
                if qty:
                    raise ValueError('entry while open')
                qty=dec(event['qty'])*event['side']
                average=dec(event['price'])
            elif kind=='exit':
                if not qty:
                    raise ValueError('exit while flat')
                gross=qty*(dec(event['price'])-average)
                close(gross,event['pnl'])
                sums['realized']+=gross
                cash+=gross
                qty=average=D(0)
            elif kind=='funding':
                history,stress=dec(event['historical_amount']),dec(event['stress_amount'])
                close(history+stress,event['amount'])
                sums['historical_funding']+=history
                sums['stress_funding']+=stress
                cash-=history+stress
            else:
                raise ValueError('unknown event')
            if kind in ('entry','exit'):
                fee=dec(event['fee'])
                sums['fees']+=fee
                cash-=fee
                for key,value in components[index].items():
                    sums[key]+=value
            close(cash,event['balance']);close(qty,event['quantity']);close(average,event['average'])
        unrealized=qty*(dec(closing_prices[row['day']])-average)
        equity=cash+unrealized
        close(equity,row['equity'])
        sums['unrealized_change']=unrealized-previous_unrealized
        sums['fill_mtm']=sums['realized']+sums['unrealized_change']
        sums['reference_mtm']=sums['fill_mtm']+sums['slippage']+sums['tick_rounding']
        sums['net']=sums['fill_mtm']-sums['fees']-sums['historical_funding']-sums['stress_funding']
        close(sums['net'],equity-previous_equity)
        result.append(dict(day=row['day'],start_equity=float(previous_equity),end_equity=float(equity),
                           **{key:float(value) for key,value in sums.items()}))
        previous_unrealized,previous_equity,previous_day=unrealized,equity,day
    if by_day or qty:
        raise ValueError('uncovered events or unclosed final position')
    return result


def aggregate(rows, label):
    if not rows:
        raise ValueError('nonempty period required')
    sums={key:float(sum((dec(row[key]) for row in rows),D(0))) for key in FLOW_KEYS}
    close(sums['net'],dec(rows[-1]['end_equity'])-dec(rows[0]['start_equity']))
    return dict(label=label,first_day=rows[0]['day'],last_day=rows[-1]['day'],days=len(rows),
                start_equity=rows[0]['start_equity'],end_equity=rows[-1]['end_equity'],**sums)


def calendar_months(rows):
    groups=defaultdict(list)
    for row in rows:
        groups[row['day'][:7]].append(row)
    return [aggregate(group,month) for month,group in groups.items()]


def episode_flow(rows, start_day, end_day):
    """Exclude starting close, include ending close. Dates are UTC."""
    selected=[row for row in rows if start_day<row['day']<=end_day]
    expected=(date.fromisoformat(end_day)-date.fromisoformat(start_day)).days
    if len(selected)!=expected or expected<=0:
        raise ValueError('episode outside observed calendar')
    return aggregate(selected,start_day+' -> '+end_day)
