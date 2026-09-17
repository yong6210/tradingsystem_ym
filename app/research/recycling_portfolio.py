"""Offline inventory recycling with independent order slots and allocated accounts.

Virtual sleeves may oppose each other; fees are charged per sleeve, without
netting savings. This is an execution proxy, never an exchange order adapter.
"""
from collections import Counter
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
import math
import numpy as np
import pandas as pd
from app.research.multistrategy import Costs, REGIMES
from app.research.scenario_inventory import PassiveOrder, PerpetualAccount, passive_fill

@dataclass(frozen=True)
class Sleeve:
    model: str
    weight: float = 1.
    regimes: tuple = ()  # Empty accepts every regime except high volatility.
    entry_mode: str = 'maker'
    ttl: int = 3
    additions: bool = True
    recycling: bool = True

@dataclass
class State:
    spec: Sleeve
    account: PerpetualAccount
    orders: dict = field(default_factory=dict)
    stop: float = 0.
    target: float = 0.
    atr: float = 0.
    seed: float = 0.
    total_bought: float = 0.
    last_trade: float = 0.
    cycle_balance: float = 0.
    risk: float = 0.
    opened: int = -1
    cooldown: int = -1
    cycles: list = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)


def simulate(minutes, signal_sets, regimes, start, end, sleeves, *, costs=Costs(), record_events=True):
    if not sleeves or any(s.weight <= 0 or s.entry_mode not in ('maker','market') or s.ttl < 1 for s in sleeves):
        raise ValueError('invalid sleeve specification')
    if not math.isclose(sum(s.weight for s in sleeves), 1., abs_tol=1e-12):
        raise ValueError('weights must sum to one; no duplicated capital')
    if len({s.model for s in sleeves}) != len(sleeves):
        raise ValueError('duplicate sleeve model')
    t=minutes.index
    lo=t.searchsorted(pd.Timestamp(start,tz='UTC')); hi=t.searchsorted(pd.Timestamp(end,tz='UTC'))
    if hi <= lo: raise ValueError('empty period')
    o,h,l,c,v=(minutes[k].to_numpy() for k in ('o','h','l','c','v'))
    states=[State(s,PerpetualAccount(initial=10000*s.weight,balance=10000*s.weight)) for s in sleeves]
    events=[]; daily=[]; monthly={}; peak=10000.; dd=0.; previous=10000.; gross_peak=0.
    net_peak=0.; turnover=0.; counts=Counter(); entry_diagnostics=[]

    def equity(price): return sum(s.account.equity(price) for s in states)

    def event(st,i,action,price,qty,side):
        nonlocal turnover
        a=st.account
        if action != 'funding': turnover += price*qty
        if record_events:
            events.append(dict(time=t[i].isoformat(),model=st.spec.model,action=action,price=float(price),qty=float(qty),side=side,
                balance=float(a.balance),average=float(a.average),remaining=float(a.qty),stop=float(st.stop)))

    def finish(st,i,reason):
        a=st.account
        if not a.qty and st.opened >= 0:
            st.cycles.append(dict(entry=t[st.opened].isoformat(),exit=t[i].isoformat(),pnl=a.balance-st.cycle_balance,
                                  reason=reason,total_bought=st.total_bought,seed=st.seed))
            st.orders.clear();st.opened=-1;st.cooldown=i+5

    def close(st,i,raw,reason):
        a=st.account;st.orders.clear()
        if a.qty:
            side,qty=a.side,a.qty;price=raw*(1-side*costs.slippage_bps/10000)
            a.reduce(qty,price,costs.taker_bps/10000)
            event(st,i,'market_'+reason,price,qty,side);st.counts[reason]+=1;finish(st,i,reason)

    def capacity(st,price,side,entry_fee=0.):
        a=st.account;distance=side*(price-st.stop)
        if distance <= 0 or price <= 0: return 0.
        stop_cost=st.stop*(costs.taker_bps+costs.slippage_bps)/10000
        room=st.risk+a.equity(st.stop)-st.cycle_balance-a.qty*stop_cost
        # No borrowing from another sleeve, and no growth of nominal allocation.
        local=max(0.,min(a.initial,a.equity(price))/price-a.qty)
        global_room=max(0.,equity(price)/price-sum(x.account.qty for x in states))
        qty=max(0.,min(local,global_room,room/(distance+stop_cost+price*entry_fee)))
        if signal_sets[st.spec.model]['rotation'] and st.seed:
            qty=min(qty,max(0.,3*st.seed-a.qty))
            if not st.spec.recycling: qty=min(qty,max(0.,3*st.seed-st.total_bought))
        return qty

    def add(st,i,qty,price,side,mode):
        nonlocal gross_peak,net_peak
        a=st.account
        if not a.qty: st.opened=i
        a.add(side,qty,price,costs.taker_bps/10000 if mode=='market' else 0.)
        st.total_bought+=qty;st.last_trade=price
        if signal_sets[st.spec.model]['rotation']:
            st.target=a.average+side*signal_sets[st.spec.model]['target_atr']*st.atr
            # Old target quantity/price is invalid after the inventory changes.
            st.orders.pop('profit',None)
        event(st,i,mode+'_add',price,qty,side)
        e=equity(price);gross=sum(x.account.qty for x in states)*price/e
        gross_peak=max(gross_peak,gross);net_peak=max(net_peak,abs(sum(x.account.qty*x.account.side for x in states))*price/e)
        # Entry fees can make post-fill gross slightly exceed the pre-fee cap;
        # capacity includes those fees in the exposure denominator below.
        assert gross <= 1+1e-8, gross

    for i in range(lo,hi):
        regime=REGIMES[int(regimes[i])]; adverse={}
        # Process known open-time exits for all sleeves before assigning new risk.
        for st in states:
            a=st.account;s=signal_sets[st.spec.model]
            if a.qty and t[i].hour%8==0 and t[i].minute==0:
                a.funding(o[i],a.side*costs.funding_bps/10000)
                event(st,i,'funding',o[i],a.qty,a.side)
            if a.qty:
                if i-st.opened>=s['max_hold']: close(st,i,o[i],'time')
                elif s['trail'] and s['decision'][i]:
                    proposal=s['close'][i]-a.side*s['stop_atr']*s['atr'][i]
                    st.stop=max(st.stop,proposal) if a.side==1 else min(st.stop,proposal)
                    if a.side*s['direction'][i]<0: close(st,i,o[i],'trend_flip')
            if a.qty and a.side*(o[i]-st.stop)<=0: close(st,i,o[i],'gap_stop')
            adverse[st.spec.model]=a.equity(o[i])

        # Shared 0.1% minute-volume budget across ALL passive fills, including exits.
        volume_left=max(0.,v[i])*.001
        for st in states:
            a=st.account;s=signal_sets[st.spec.model];spec=st.spec
            eligible=regime!='high_volatility' and (not spec.regimes or regime in spec.regimes)
            if not eligible: st.orders.pop('add',None)
            side=int(s['side'][i])
            if side:
                reason='eligible'
                if not eligible: reason='regime'
                elif a.qty: reason='own_position'
                elif i<=st.cooldown: reason='cooldown'
                elif 'add' in st.orders: reason='pending_entry'
                st.counts['signal_'+reason]+=1
                if record_events: entry_diagnostics.append(dict(time=t[i].isoformat(),model=spec.model,reason=reason))
            if not a.qty and 'add' not in st.orders and eligible and i>st.cooldown and side:
                st.atr=float(s['atr'][i]);st.cycle_balance=a.balance;st.risk=max(0.,min(a.initial,a.balance)*.005)
                st.seed=0.;st.total_bought=0.
                price=o[i]*(1+side*costs.slippage_bps/10000) if spec.entry_mode=='market' else s['close'][i]-side*.1*st.atr
                st.stop=price-side*s['stop_atr']*st.atr
                fee=costs.taker_bps/10000 if spec.entry_mode=='market' else 0.
                qty=capacity(st,price,side,fee)
                # Include entry fee in local/global notional caps, not only stop budget.
                if fee: qty=min(qty,max(0.,equity(price)/price-sum(x.account.qty for x in states))/(1+fee))
                if s['rotation']:qty/=3
                st.seed=qty;st.target=price+side*s['target_atr']*st.atr if s['target_atr'] else 0.
                if qty>1e-9 and st.stop>0:
                    if spec.entry_mode=='market': add(st,i,qty,price,side,'market')
                    else: st.orders['add']=PassiveOrder(side,qty,price,i-1,'entry')
                else:st.counts['risk_rejected']+=1
            elif a.qty and s['rotation'] and spec.additions and eligible and s['decision'][i] and 'add' not in st.orders:
                # After a trim, last_trade is the sell price: a one-ATR retrace
                # can replenish the sold inventory, still under the original stop.
                if a.side*(s['close'][i]-st.last_trade)<=-st.atr:
                    price=s['close'][i]-a.side*.1*st.atr
                    qty=min(st.seed,capacity(st,price,a.side))
                    if qty>1e-9:st.orders['add']=PassiveOrder(a.side,qty,price,i-1,'reentry')
                    else:st.counts['risk_rejected']+=1
            # Profit order slot is independent of the add slot. Quantity is frozen
            # until fill, expiry, or cancellation following a new inventory fill.
            if a.qty and st.target and i>st.opened and 'profit' not in st.orders:
                qty=min(st.seed,a.qty/2) if s['rotation'] and a.qty>st.seed*.6 else a.qty
                price=max(st.target,o[i]*1.0001) if a.side==1 else min(st.target,o[i]*.9999)
                st.orders['profit']=PassiveOrder(-a.side,qty,price,i-1,'profit',True)
            # Fill additions first if both add and stop can trade within a bar.
            # A changed average cancels old targets; never assume a same-bar rebound.
            order=st.orders.get('add')
            if order:
                qty,status=passive_fill(order,SimpleNamespace(o=o[i],h=h[i],l=l[i],v=v[i]),i,ttl=spec.ttl,
                    penetration_bps=costs.penetration_bps,fill_fraction=costs.fill_fraction)
                if status in ('expired','post_only_rejected'):
                    st.counts[status]+=1;st.orders.pop('add',None)
                elif qty>0:
                    qty=min(qty,volume_left,capacity(st,order.price,order.side))
                    if qty>1e-9:
                        add(st,i,qty,order.price,order.side,'maker');order.remaining-=qty;volume_left-=qty
                        st.counts[order.reason+'_fills']+=1
                        if order.remaining<1e-9:st.orders.pop('add',None)
                    else:st.counts['risk_rejected']+=1
            if a.qty:
                # Bound path uncertainty before reductions, clipped at stop.
                worst=max(l[i],st.stop) if a.side==1 else min(h[i],st.stop)
                adverse[spec.model]=min(adverse[spec.model],a.equity(worst))
                if (l[i]<=st.stop if a.side==1 else h[i]>=st.stop):close(st,i,st.stop,'stop')
            order=st.orders.get('profit')
            if order and a.qty:
                qty,status=passive_fill(order,SimpleNamespace(o=o[i],h=h[i],l=l[i],v=v[i]),i,ttl=spec.ttl,
                    penetration_bps=costs.penetration_bps,fill_fraction=costs.fill_fraction)
                if status in ('expired','post_only_rejected'):
                    st.orders.pop('profit',None);st.counts[status]+=1
                elif qty>0:
                    qty=min(qty,volume_left,a.qty)
                    if qty>1e-9:
                        side=a.side;a.reduce(qty,order.price);event(st,i,'maker_reduce',order.price,qty,side)
                        order.remaining-=qty;volume_left-=qty;st.last_trade=order.price;st.counts['profit_fills']+=1
                        if order.remaining<1e-9:
                            st.orders.pop('profit',None);st.target=order.price+side*.25*st.atr
                        finish(st,i,'profit')
            if i==hi-1:close(st,i,c[i],'end')
            a.check(c[i]);adverse[spec.model]=min(adverse[spec.model],a.equity(c[i]))
        eq=equity(c[i]);dd=max(dd,1-min(eq,sum(adverse.values()))/peak);peak=max(peak,eq)
        month=t[i].strftime('%Y-%m');monthly.setdefault(month,dict(start=previous,end=eq))['end']=eq;previous=eq
        if i==hi-1 or t[i+1].date()!=t[i].date():daily.append(dict(date=str(t[i].date()),equity=eq))
    result_sleeves={}
    for st in states:
        a=st.account
        assert math.isclose(sum(x['pnl'] for x in st.cycles),a.balance-a.initial,abs_tol=1e-6)
        result_sleeves[st.spec.model]=dict(spec=asdict(st.spec),initial=a.initial,final=a.balance,pnl=a.balance-a.initial,
            realized=a.realized,fees=a.fees,funding=a.funding_paid,cycles=st.cycles,counts=dict(st.counts))
    returns=np.diff([10000.]+[x['equity'] for x in daily])/np.array([10000.]+[x['equity'] for x in daily[:-1]])
    std=returns.std(ddof=1) if len(returns)>1 else 0.
    monthly={k:x['end']/x['start']-1 for k,x in monthly.items()}
    assert math.isclose(math.prod(1+x for x in monthly.values()),eq/10000,abs_tol=1e-8)
    return dict(return_pct=(eq/10000-1)*100,max_drawdown_bound_pct=dd*100,final_equity=eq,
        sharpe=float(returns.mean()/std*np.sqrt(365)) if std>1e-12 else 0.,daily=daily,monthly=monthly,
        gross_entry_exposure_peak=gross_peak,net_entry_exposure_peak=net_peak,turnover=turnover,
        sleeves=result_sleeves,events=events,entry_diagnostics=entry_diagnostics,costs=asdict(costs))
