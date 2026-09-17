"""Minute OHLC market-fill reference engine; no maker/liquidation claims."""
from collections import Counter
from dataclasses import asdict
import math
import numpy as np
import pandas as pd
from .account import Account, Costs, replay
from .risk import Risk, size_order


def policies(minutes, bank):
    f=bank[240]
    valid=f.ema80.notna() & f.atr.notna() & f.er.notna() & f.c.shift(20).notna()
    direction=np.sign(f.ema20-f.ema80)
    filtered=np.where(((f.ema20-f.ema80).abs()/f.atr>.5)&((f.c-f.ema20)*direction>0)&(f.er>.2),direction,0)
    momentum=np.sign(f.c/f.c.shift(20)-1)
    positions=minutes.index.get_indexer(f.index)+1
    result={}
    for name,sides in [('T0',direction),('T1',filtered),('T2',momentum)]:
        result[name]={int(pos):(int(side),float(close),float(atr))
                      for pos,side,close,atr,ok in zip(positions,sides,f.c,f.atr,valid)
                      if ok and pos>0 and pos<len(minutes)}
    return result


def simulate(minutes, decisions, start, end, costs=Costs(), risk=Risk()):
    lower=int(minutes.index.searchsorted(start))
    upper=int(minutes.index.searchsorted(end))
    if lower>=upper:
        raise ValueError('empty evaluation')
    opens,highs,lows,closes=(minutes[k].to_numpy() for k in ('o','h','l','c'))
    # Epoch-minute arithmetic avoids constructing timestamp objects inside every bar.
    epoch_minutes=minutes.index.asi8//60_000_000_000
    account=Account(risk.initial)
    peak=risk.initial
    maximum_dd=0.0
    warned=False
    halted=False
    day_halted=False
    day_start=risk.initial
    current_day=None
    stop=0.0
    entry_minute=None
    entry_balance=None
    entry_info=None
    trades=[]
    daily=[]
    rejections=[]
    actions=Counter()
    active_minutes=0
    summed_notional=0.0
    peak_notional=0.0
    final_day_equity=risk.initial
    halt_time=None

    def stamp(i):
        return minutes.index[i].isoformat()

    def observe(equity, i):
        nonlocal peak,maximum_dd,warned,halted,day_halted,halt_time
        peak=max(peak,equity)
        dd=max(0.,1-equity/peak)
        maximum_dd=max(maximum_dd,dd)
        if dd>=risk.warning-1e-12:
            warned=True
        if dd>=risk.halt-1e-12 or equity<=0:
            if not halted:
                halt_time=stamp(i)
            halted=True
        if equity<=day_start*(1-risk.daily_stop)+1e-10:
            day_halted=True

    def close_position(i, reference, reason):
        nonlocal stop,entry_minute,entry_balance,entry_info
        side=1 if account.quantity>0 else -1
        account.close(stamp(i),costs.fill(reference,-side),costs.fee_bps,reason)
        trades.append(dict(**entry_info,exit_time=stamp(i),exit_minute=i,reason=reason,
                           net_pnl=account.balance-entry_balance,ending_balance=account.balance))
        actions[reason]+=1
        stop=0.0
        entry_minute=None
        entry_balance=None
        entry_info=None
        observe(account.balance,i)

    def protective_line():
        if not account.quantity:
            return None
        threshold=max(peak*(1-risk.halt),day_start*(1-risk.daily_stop))
        risk_price=account.average+(threshold-account.balance)/account.quantity
        side=1 if account.quantity>0 else -1
        selected=max(stop,risk_price) if side==1 else min(stop,risk_price)
        reason='risk_stop' if selected==risk_price else 'price_stop'
        return selected,reason

    for i in range(lower,upper):
        op,hi,lo,cl=float(opens[i]),float(highs[i]),float(lows[i]),float(closes[i])
        day=int(epoch_minutes[i]//1440)
        if day!=current_day:
            if current_day is not None:
                daily.append(dict(day=str(pd.Timestamp(current_day*1440,unit='m',tz='UTC').date()),equity=final_day_equity,halted=halted))
            current_day=day
            day_start=account.equity(op)
            day_halted=False
        peak=max(peak,account.equity(op))
        if epoch_minutes[i]%480==0:
            account.pay_funding(stamp(i),op,costs.funding_bps_8h)
        closed_this_bar=False
        # Existing positions encounter open gaps before new decisions.
        if account.quantity:
            line,reason=protective_line()
            side=1 if account.quantity>0 else -1
            if side*(op-line)<=0:
                observe(account.equity(op),i)
                close_position(i,op,reason+'_gap')
                closed_this_bar=True
        observe(account.equity(op),i)
        if account.quantity and (halted or day_halted):
            close_position(i,op,'risk_halt')
            closed_this_bar=True
        if account.quantity and i-entry_minute>=risk.maximum_hold_minutes:
            close_position(i,op,'time_exit')
            closed_this_bar=True
        if i in decisions:
            side,decision_close,atr=decisions[i]
            actions['decisions']+=1
            if account.quantity and (side==0 or np.sign(account.quantity)!=side):
                close_position(i,op,'neutral_exit' if side==0 else 'reverse_exit')
            if side and not account.quantity and not closed_this_bar:
                if halted or day_halted:
                    actions['halted_entry']+=1
                else:
                    proposal=size_order(op,decision_close,atr,side,account.balance,warned,costs,risk)
                    if not proposal['approved']:
                        actions[proposal['reason']]+=1
                        rejections.append(dict(time=stamp(i),**proposal))
                    else:
                        entry_balance=account.balance
                        account.enter(stamp(i),side,proposal['quantity'],proposal['entry'],costs.fee_bps)
                        stop=proposal['stop']
                        entry_minute=i
                        entry_info=dict(entry_time=stamp(i),entry_minute=i,side=side,quantity=proposal['quantity'],
                                        entry_price=proposal['entry'],stop=stop,planned_loss=proposal['planned_loss'],budget=proposal['budget'])
                        actions['entries']+=1
                        observe(account.equity(op),i)
                        if halted or day_halted:
                            close_position(i,op,'entry_cost_halt')
        if account.quantity:
            active_minutes+=1
            notional=abs(account.quantity)*op
            summed_notional+=notional
            peak_notional=max(peak_notional,notional)
            line,reason=protective_line()
            side=1 if account.quantity>0 else -1
            touched=lo<=line if side==1 else hi>=line
            if touched:
                observe(account.equity(line),i)
                close_position(i,line,reason)
            else:
                adverse=lo if side==1 else hi
                observe(account.equity(adverse),i)
        observe(account.equity(cl),i)
        final_day_equity=account.equity(cl)
    preclose_equity=account.equity(float(closes[upper-1]))
    if account.quantity:
        close_position(upper-1,float(closes[upper-1]),'end_exit')
    final_day_equity=account.balance
    daily.append(dict(day=str(pd.Timestamp(current_day*1440,unit='m',tz='UTC').date()),equity=final_day_equity,halted=halted))
    reconciliation=replay(account.events,risk.initial)
    if not math.isclose(sum(t['net_pnl'] for t in trades),account.balance-risk.initial,abs_tol=1e-7):
        raise ValueError('cycle PnL attribution failed')
    return dict(metrics=dict(initial=risk.initial,final_equity=account.balance,preclose_equity=preclose_equity,
                             return_pct=(account.balance/risk.initial-1)*100,max_drawdown_pct=maximum_dd*100,
                             cycles=len(trades),fees=account.fees,funding=account.funding,realized=account.realized,
                             active_fraction=active_minutes/(upper-lower),mean_notional=summed_notional/(upper-lower),
                             peak_notional=peak_notional,drawdown_halted=halted,halt_time=halt_time,
                             warned=warned,last_exit=trades[-1]['exit_time'] if trades else None,
                             actions=dict(actions),costs=asdict(costs),risk=asdict(risk)),
                events=account.events,trades=trades,daily=daily,rejections=rejections,verification=reconciliation)
