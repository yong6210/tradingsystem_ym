"""E039: frozen E015 path logic with explicit operating cash charges.

The original engine remains unchanged. Zero-charge runs must reproduce E038.
"""
from collections import Counter
from dataclasses import asdict
import math
import numpy as np
import pandas as pd
from ..baseline.account import Costs
from .operating_account import Account, replay
from ..baseline.risk import Risk, size_order
from ..comparison.funding import funding_schedule, settle


def simulate(minutes, decisions, start, end, costs=Costs(), risk=Risk(), *, funding=(), path="OHLC", operating_debits=None):
    if path not in ("OHLC", "OLHC"): raise ValueError("fixed intrabar path required")
    lower=int(minutes.index.searchsorted(start))
    upper=int(minutes.index.searchsorted(end))
    if lower>=upper:
        raise ValueError('empty evaluation')
    operating_debits=dict(operating_debits or {})
    for index,amount in operating_debits.items():
        if not isinstance(index,int) or not lower<=index<upper or not math.isfinite(amount) or amount<0:
            raise ValueError('invalid operating debit')
    opens,highs,lows,closes=(minutes[k].to_numpy() for k in ('o','h','l','c'))
    # Epoch-minute arithmetic avoids constructing timestamp objects inside every bar.
    epoch_minutes=minutes.index.asi8//60_000_000_000
    settlements=funding_schedule(minutes.index, funding)
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
    entry_operating=0.0
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
    path_stops=[]
    favorable_peak_updates=0

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
                           net_pnl=account.balance-entry_balance+account.operating-entry_operating,ending_balance=account.balance))
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
        for event in settlements.get(i, ()):
            settle(account, stamp(i), event, costs.funding_bps_8h)
        if operating_debits.get(i,0):
            account.pay_operating(stamp(i),operating_debits[i])
            actions['operating_debit']+=1
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
                        entry_operating=account.operating
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
            side=1 if account.quantity>0 else -1
            points=(op,hi,lo,cl) if path=="OHLC" else (op,lo,hi,cl)
            for leg,(origin,destination) in enumerate(zip(points,points[1:])):
                line,reason=protective_line()
                # Entry costs can put a newly created stop beyond the current
                # market. Such a stop executes from the current price, not at a
                # fictitious better stop price. Existing gaps were handled above.
                breached_at_origin=side*(origin-line)<=0
                if breached_at_origin or side*(destination-line)<=0:
                    reference=origin if breached_at_origin else line
                    path_stops.append(dict(minute=i,time=stamp(i),leg=leg,
                        origin=origin,destination=destination,protective_line=line,
                        reference=reference,breached_at_origin=breached_at_origin,
                        peak_before=peak,day_start=day_start,balance_before=account.balance,
                        signed_quantity=account.quantity,average=account.average,
                        initial_stop=stop,reason=reason,event_index=len(account.events)))
                    observe(account.equity(reference),i)
                    close_position(i,reference,reason+('_gap' if breached_at_origin else ''))
                    break
                old_peak=peak
                observe(account.equity(destination),i)
                if peak>old_peak:
                    favorable_peak_updates+=1
        observe(account.equity(cl),i)
        final_day_equity=account.equity(cl)
    preclose_equity=account.equity(float(closes[upper-1]))
    if account.quantity:
        close_position(upper-1,float(closes[upper-1]),'end_exit')
    final_day_equity=account.balance
    daily.append(dict(day=str(pd.Timestamp(current_day*1440,unit='m',tz='UTC').date()),equity=final_day_equity,halted=halted))
    reconciliation=replay(account.events,risk.initial)
    if not math.isclose(sum(t['net_pnl'] for t in trades),account.balance-risk.initial+account.operating,abs_tol=1e-7):
        raise ValueError('cycle PnL attribution failed')
    return dict(path_stops=path_stops, path_diagnostics=dict(path=path, favorable_peak_updates=favorable_peak_updates),
                metrics=dict(funding_timing='FIRST_MINUTE_OPEN_AT_OR_AFTER_EVENT', risk_price_basis='CONTRACT_PRICE_NOT_LIQUIDATION', initial=risk.initial,final_equity=account.balance,preclose_equity=preclose_equity,
                             return_pct=(account.balance/risk.initial-1)*100,max_drawdown_pct=maximum_dd*100,
                             operating_cost=account.operating,cycles=len(trades),fees=account.fees,funding=account.funding,realized=account.realized,
                             active_fraction=active_minutes/(upper-lower),mean_notional=summed_notional/(upper-lower),
                             peak_notional=peak_notional,drawdown_halted=halted,halt_time=halt_time,
                             warned=warned,last_exit=trades[-1]['exit_time'] if trades else None,
                             actions=dict(actions),costs=asdict(costs),risk=asdict(risk)),
                events=account.events,trades=trades,daily=daily,rejections=rejections,verification=reconciliation)
