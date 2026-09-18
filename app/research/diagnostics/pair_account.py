"""Conditional two-futures account; no network or live execution adapter."""
from decimal import Decimal as D,ROUND_CEILING,ROUND_FLOOR
import heapq
import json
import math
import numpy as np
import pandas as pd

from .pair_feasibility import size_pair,HOUR

FEE=D('.00025')
TICKS=dict(btc=D('.1'),eth=D('.01'))


def execution_price(row,leg,side,slip,closing=False):
    reference=D(str(row[leg+('_close' if closing else '_open')]))
    raw=reference*(1+side*slip);tick=TICKS[leg]
    return (raw/tick).to_integral_value(rounding=ROUND_CEILING if side==1 else ROUND_FLOOR)*tick


def signals(rows):
    values=np.log(np.array([float(r['eth_close']) for r in rows])/np.array([float(r['btc_close']) for r in rows]))
    prior=pd.Series(values).shift(1).rolling(720,min_periods=720)
    mu,sd=prior.mean().to_numpy(),prior.std(ddof=0).to_numpy()
    return [float((v-m)/s) if math.isfinite(s) and s>1e-12 else None for v,m,s in zip(values,mu,sd)]


class Book:
    def __init__(self,state=None):
        self.s=state or dict(wallet=dict(btc='400',eth='400'),position=dict(btc='0',eth='0'),
            average=dict(btc='0',eth='0'),outside='200',fills={},funding={},costs={},
            peak='1000',day=None,day_start='1000',day_halt=False,halt=None,cooldown=0,cycle=None)
        self.ledger=[]
    def restore(self):
        return Book(json.loads(json.dumps(self.s)))
    def equity(self,row,slip,closing=False):
        suffix='close' if closing else 'open'
        total=D(self.s['outside']);margins={}
        for leg in ('btc','eth'):
            q=D(self.s['position'][leg]);p=D(str(row[leg+'_'+suffix]))
            exit_price=execution_price(row,leg,-1 if q>0 else 1,slip,closing)
            avg=D(self.s['average'][leg]);cash=D(self.s['wallet'][leg])
            total+=cash+q*(exit_price-avg)-abs(q)*exit_price*FEE
            margins[leg]=cash+q*(D(str(row[leg+'_mark_'+suffix]))-avg)
        return total,margins
    def fill(self,identity,leg,side,quantity,price,t,cycle_id):
        quantity,price=D(str(quantity)),D(str(price))
        if side not in (-1,1) or not quantity.is_finite() or not price.is_finite() or quantity<=0 or price<=0 or type(t)is not int:raise ValueError('invalid fill')
        record=dict(id=identity,type='fill',leg=leg,side=side,qty=str(quantity),price=str(price),
            quote=str(quantity*price),fee=str(quantity*price*FEE),time_ms=t,cycle_id=cycle_id)
        if identity in self.s['fills']:
            if self.s['fills'][identity]!=record:raise ValueError('conflicting fill')
            return
        old=D(self.s['position'][leg]);avg=D(self.s['average'][leg]);cash=D(self.s['wallet'][leg])
        signed=side*quantity;new=old+signed
        if old and old*signed<0:
            if quantity>abs(old):raise ValueError('position reversal/overclose')
            cash+=quantity*(price-avg)*(1 if old>0 else -1)
            if not new:avg=D(0)
        else:avg=(abs(old)*avg+quantity*price)/abs(new)
        self.s['wallet'][leg]=str(cash-quantity*price*FEE)
        self.s['position'][leg]=str(new);self.s['average'][leg]=str(avg)
        self.s['fills'][identity]=record;self.ledger.append(record)
    def fund(self,event,t,extra):
        leg=event['leg'];identity=leg+'/'+str(event['time_ms'])
        inp={k:str(event[k]) for k in ('mark','rate')}
        if event['time_ms']>t or any(not D(v).is_finite() for v in inp.values()) or D(inp['mark'])<=0:raise ValueError('invalid settlement')
        inp['extra']=str(extra)
        if identity in self.s['funding']:
            if self.s['funding'][identity]['input']!=inp:raise ValueError('conflicting settlement')
            return
        q=sum((D(f['qty'])*f['side'] for f in self.s['fills'].values() if f['leg']==leg and f['time_ms']<event['time_ms']),D(0))
        historical=-q*D(inp['mark'])*D(inp['rate']);additional=abs(q)*D(inp['mark'])*extra
        amount=historical-additional
        record=dict(type='funding',id=identity,leg=leg,time_ms=t,settlement_ms=event['time_ms'],
            input=inp,qty=str(q),historical=str(historical),additional=str(additional),amount=str(amount),
            cycle_id=self.s['cycle']['id'] if self.s['cycle'] else None)
        self.s['wallet'][leg]=str(D(self.s['wallet'][leg])+amount)
        self.s['funding'][identity]=record;self.ledger.append(record)
    def cost(self,identity,amount,t):
        amount=D(str(amount))
        if identity in self.s['costs']:
            if self.s['costs'][identity]!=str(amount):raise ValueError('conflicting cost')
            return
        self.s['outside']=str(D(self.s['outside'])-amount);self.s['costs'][identity]=str(amount)
        self.ledger.append(dict(type='cost',id=identity,amount=str(amount),time_ms=t))
    def risk(self,row,slip,t):
        equity,margin=self.equity(row,slip);s=self.s
        day=t//86400000
        if s['day']!=day:s['day']=day;s['day_start']=str(equity);s['day_halt']=False
        s['peak']=str(max(D(s['peak']),equity))
        if equity<=D(s['peak'])*D('.92'):s['halt']=s['halt'] or 'DRAWDOWN'
        for leg in ('btc','eth'):
            reserve=abs(D(s['position'][leg]))*D(str(row[leg+'_mark_open']))*D('.01075')
            if margin[leg]<=reserve:s['halt']=s['halt'] or 'MARGIN'
        if equity<=D(s['day_start'])*D('.98'):s['day_halt']=True
        reason=s['halt'] or ('DAILY' if s['day_halt'] else None)
        if not reason and s['cycle']:
            pnl=equity-D(s['outside'])-D(s['cycle']['start_wallets'])
            if pnl<=-5:reason='PAIR_LOSS'
        return reason


def run(rows,funding,contracts,*,slip_bps,extra_funding_bps,monthly_cost,signal_values=None):
    z=signals(rows) if signal_values is None else signal_values
    if len(z)!=len(rows):raise ValueError('signal length')
    book=Book();slip=D(str(slip_bps))/10000;extra=D(str(extra_funding_bps))/10000
    orders=[];cycles=[];hourly=[];rejections=[];fund_by={};number=0
    for e in funding:
        if rows[0]['time_ms']<=e['time_ms']<rows[-1]['time_ms']+HOUR:
            fund_by.setdefault(e['time_ms']//HOUR,[]).append(e)
    for i,row in enumerate(rows):
        t0=row['time_ms'];heap=[];serial=0
        # Daily baseline is before this instant's funding and operating charge.
        book.risk(row,slip,t0)
        def schedule(t,priority,kind,value=None):
            nonlocal serial
            serial+=1;heapq.heappush(heap,(t,priority,serial,kind,value))
        def order(leg,side,qty,t,role,emergency=False):
            o=dict(id=len(orders)+1,leg=leg,side=side,qty=str(qty),created_ms=t,
                fill_ms=t+(1 if emergency else 3001),role=role,status='PENDING',
                conditional_path='MARKET' if emergency else 'UNFILLED_LIMIT_CANCEL_MARKET',
                cycle_id=book.s['cycle']['id'])
            orders.append(o);schedule(o['fill_ms'],1,'fill',o)
        def exiting(reason,t,emergency):
            cycle=book.s['cycle']
            if not cycle or cycle['phase']=='EXITING':return
            for o in orders:
                if o['status']=='PENDING':o['status']='CANCELED_UNFILLED_MODEL'
            cycle.update(phase='EXITING',exit_reason=reason,emergency=emergency)
            for leg in ('btc','eth'):
                q=D(book.s['position'][leg])
                if q:order(leg,-1 if q>0 else 1,abs(q),t,'EXIT',emergency);return
            finalize(t)
        def finalize(t):
            cycle=book.s['cycle']
            if any(D(q) for q in book.s['position'].values()):raise ValueError('false flat')
            net=sum(map(D,book.s['wallet'].values()))-D(cycle['start_wallets'])
            cycles.append(dict(id=cycle['id'],entry_time_ms=cycle.get('first_fill_ms'),exit_time_ms=t,
                sign=cycle['sign'],net_pnl=str(net),reason=cycle['exit_reason']))
            book.s['cycle']=None;book.s['cooldown']=((t+HOUR-1)//HOUR+1)*HOUR
        def check(t):
            reason=book.risk(row,slip,t)
            if reason and book.s['cycle']:exiting(reason,t,True)
        schedule(t0,3,'decision')
        for e in fund_by.get(t0//HOUR,[]):schedule(e['time_ms'],0,'funding',e)
        next_hour=pd.Timestamp(t0+HOUR,unit='ms',tz='UTC')
        if monthly_cost and next_hour.month!=pd.Timestamp(t0,unit='ms',tz='UTC').month:
            schedule(t0,0,'cost',pd.Timestamp(t0,unit='ms',tz='UTC').strftime('%Y-%m'))
        while heap:
            t,_,_,kind,value=heapq.heappop(heap)
            if t>=t0+HOUR:raise ValueError('order path exceeds hour')
            if kind=='funding':book.fund(value,t,extra);check(t);continue
            if kind=='cost':book.cost(value,monthly_cost,t);check(t);continue
            if kind=='fill':
                o=value
                if o['status']!='PENDING':continue
                cycle=book.s['cycle'];leg=o['leg'];q=D(o['qty'])
                price=execution_price(row,leg,o['side'],slip)
                book.fill(str(o['id']),leg,o['side'],q,price,t,o['cycle_id']);o['status']='FILLED'
                cycle.setdefault('first_fill_ms',t)
                check(t)
                if o['role']=='ENTRY':
                    if cycle['phase']=='EXITING':continue
                    if leg=='btc':
                        order('eth',-cycle['sign'],D(cycle['eth_qty']),t+1,'ENTRY')
                    else:cycle['phase']='OPEN'
                else:
                    other='eth' if leg=='btc' else 'btc';remaining=D(book.s['position'][other])
                    if remaining:order(other,-1 if remaining>0 else 1,abs(remaining),t+1,'EXIT',cycle['emergency'])
                    else:finalize(t)
                continue
            check(t);cycle=book.s['cycle'];signal=z[i-1] if i>0 else None
            if i==len(rows)-1:
                if cycle:exiting('REGISTERED_END',t,False)
                continue
            if cycle:
                if cycle['phase']!='OPEN':continue
                signed=cycle['sign']*signal if signal is not None else None
                reason=('INVALID_SIGNAL' if signed is None else 'REVERT' if signed<=.5 else
                    'EXTREME' if signed>=4 else 'TIME' if t-cycle['first_fill_ms']>=168*HOUR else None)
                if reason:exiting(reason,t,reason in ('INVALID_SIGNAL','EXTREME'))
                continue
            if book.s['halt'] or book.s['day_halt'] or t<book.s['cooldown'] or signal is None or not 2<=abs(signal)<4:continue
            sizing=size_pair(row['btc_open'],row['eth_open'],contracts['BTCUSDC'],contracts['ETHUSDC'])
            reasons=list(sizing['reasons'])
            sign=1 if signal>0 else -1
            planned={leg:D(sizing[leg+'_qty'])*execution_price(row,leg,sign if leg=='btc' else -sign,slip) for leg in ('btc','eth')}
            if max(planned.values()) and abs(planned['btc']-planned['eth'])>D('.03')*max(planned.values()):reasons.append('execution_notional_mismatch')
            for leg in ('btc','eth'):
                worst=execution_price(row,leg,1,D('.0005'))
                if D(sizing[leg+'_qty'])*worst>200:reasons.append(leg+'_TICK_CAP')
                needed=D(sizing[leg+'_qty'])*max(worst,D(str(row[leg+'_mark_open'])))*(1+FEE)
                if needed>D(book.s['wallet'][leg]):reasons.append(leg+'_CURRENT_MARGIN')
            if reasons:rejections.append(dict(time_ms=t,reasons=reasons));continue
            number+=1
            book.s['cycle']=dict(id=number,sign=sign,phase='ENTERING',eth_qty=sizing['eth_qty'],
                start_wallets=str(sum(map(D,book.s['wallet'].values()))))
            order('btc',sign,D(sizing['btc_qty']),t,'ENTRY')
        equity,margins=book.equity(row,slip,closing=True)
        hourly.append(dict(time_ms=t0+HOUR-1,day=row['hour'][:10],equity=str(equity),
            wallet=dict(book.s['wallet']),position=dict(book.s['position']),average=dict(book.s['average']),outside=book.s['outside'],
            margin={k:str(v) for k,v in margins.items()},halt=book.s['halt'],day_halt=book.s['day_halt']))
    if book.s['cycle'] or any(D(q) for q in book.s['position'].values()):raise ValueError('terminal residual')
    return dict(hourly=hourly,ledger=book.ledger,orders=orders,cycles=cycles,rejections=rejections,state=book.s)
