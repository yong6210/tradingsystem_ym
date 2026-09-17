"""Minute market-fill proxy connecting v1 order contracts to an account.

RESTING_LIMIT is rejected: minute touches are not exchange fill evidence.
Legacy E005 engine/source is immutable and used separately for reproduction.
"""
from collections import Counter
from dataclasses import asdict
from decimal import Decimal as D
import math
import numpy as np
import pandas as pd
from ..baseline.account import Account,Costs,replay
from ..baseline.risk import Risk
from ..comparison.funding import funding_schedule,settle
from ..execution.order_rules import (TakeProfit,EntryBook,reserve_entry,finish_cycle,
                                    prepare_cycle,Bar,evaluate_bar)
from .sizing import size_plan


def simulate(minutes, decisions, start, end, rules, costs=Costs(), risk=Risk(), *, funding=(), marks=None):
    if rules.take_profit==TakeProfit.RESTING_LIMIT:
        raise ValueError('RESTING_LIMIT requires fill evidence; OHLC comparison disabled')
    if rules.decision_delay_ms!=60000 or rules.maximum_hold_ms%60000 or float(rules.tick)!=costs.tick:
        raise ValueError('unsupported minute grid or mismatched price tick')
    lower,upper=map(int,(minutes.index.searchsorted(start),minutes.index.searchsorted(end)))
    if lower>=upper or marks is None or not marks.index.equals(minutes.index):
        raise ValueError('empty window or missing aligned mark data')
    if not np.isfinite(marks.iloc[lower:upper].to_numpy()).all(): raise ValueError('mark data gap')
    values=minutes[['o','h','l','c']].to_numpy();mark_values=marks.to_numpy()
    times=minutes.index.asi8//1_000_000
    settlements=funding_schedule(minutes.index,funding)
    account=Account(risk.initial);book=EntryBook();plan=None;info=None;entered=None;entry_cash=None
    peak=risk.initial;maxdd=0.;warned=False;halted=False;day_halted=False;halt_time=None
    day=None;day_start=risk.initial;day_equity=risk.initial;scheduled=None
    trades=[];daily=[];rejections=[];actions=Counter();active=0
    notional_sum=0.;notional_peak=0.
    hourly_closes={s.latest.available_ms for s in decisions.values()}

    def stamp(i): return minutes.index[i].isoformat()

    def observe(equity,i):
        nonlocal peak,maxdd,warned,halted,day_halted,halt_time
        peak=max(peak,equity);dd=max(0.,1-equity/peak);maxdd=max(maxdd,dd)
        warned=warned or dd>=risk.warning-1e-12
        if dd>=risk.halt-1e-12 or equity<=0:
            if not halted: halt_time=stamp(i)
            halted=True
        if equity<=day_start*(1-risk.daily_stop)+1e-10: day_halted=True

    def close(i,reference,reason,*,intrabar=False,ambiguous=False):
        nonlocal book,plan,info,entered,entry_cash,scheduled
        account.close(stamp(i),costs.fill(reference,-plan.side),costs.fee_bps,reason)
        confirmed=int(times[i])+60000 if intrabar else int(times[i])
        trades.append(dict(**info,exit_time=stamp(i),exit_minute=i,reason=reason,
                           net_pnl=account.balance-entry_cash,ending_balance=account.balance,
                           exit_confirmed_ms=confirmed,ambiguous=ambiguous))
        book=finish_cycle(book,plan.intent_id,confirmed_ms=confirmed,reconciled_flat_and_orders_clear=True)
        actions[reason]+=1
        if ambiguous: actions['ambiguous_exits']+=1
        plan=info=entered=entry_cash=scheduled=None
        observe(account.balance,i)

    def risk_line():
        threshold=max(peak*(1-risk.halt),day_start*(1-risk.daily_stop))
        return account.average+(threshold-account.balance)/account.quantity

    for i in range(lower,upper):
        op,hi,lo,cl=map(float,values[i]);now=int(times[i]);new_day=now//86400000
        if new_day!=day:
            if day is not None:
                daily.append(dict(day=str(pd.Timestamp(day,unit='D',tz='UTC').date()),equity=day_equity,halted=halted))
            day=new_day;day_start=account.equity(op);day_halted=False
        peak=max(peak,account.equity(op))
        for event in settlements.get(i,()): settle(account,stamp(i),event,costs.funding_bps_8h)
        closed=False
        observe(account.equity(op),i)
        if account.quantity:
            line=risk_line()
            if plan.side*(op-float(plan.stop))<=0:
                close(i,op,'STOP_GAP');closed=True
            elif halted or day_halted or plan.side*(op-line)<=0:
                close(i,op,'ACCOUNT_RISK_GAP');closed=True
            elif now>=entered+rules.maximum_hold_ms:
                close(i,op,'TIME_LIMIT');closed=True
            elif scheduled is not None and now>=scheduled:
                close(i,op,'TARGET_CLOSE_CONFIRMED');closed=True
        if i in decisions:
            signal=decisions[i];actions['decisions']+=1
            if account.quantity and signal.side!=plan.side:
                close(i,op,'SIGNAL_NEUTRAL' if not signal.side else 'SIGNAL_REVERSE');closed=True
            if signal.side and not account.quantity and not closed:
                if halted or day_halted:
                    actions['halted_entry']+=1
                else:
                    candidate_book,reservation=reserve_entry(book,signal,rules,now_ms=now,
                        reconciled_flat_and_orders_clear=True,risk_approved=True,signal_valid=True)
                    if not reservation.approved:
                        actions[reservation.reason]+=1
                    else:
                        entry=costs.fill(op,signal.side)
                        try:
                            candidate=prepare_cycle(signal,rules,reservation.intent_id,D(str(entry)))
                        except ValueError as exc:
                            proposal=dict(approved=False,reason='invalid_target_or_stop',detail=str(exc))
                        else:
                            proposal=size_plan(candidate,entry,float(mark_values[i]),account.balance,warned,costs,risk)
                        if not proposal['approved']:
                            rejections.append(dict(time=stamp(i),**proposal));actions[proposal['reason']]+=1
                        else:
                            # No order was reserved/sent on a rejected preflight.
                            book=candidate_book;plan=candidate;entered=now;entry_cash=account.balance
                            account.enter(stamp(i),signal.side,proposal['quantity'],entry,costs.fee_bps)
                            info=dict(entry_time=stamp(i),entry_minute=i,side=signal.side,quantity=proposal['quantity'],
                                entry_price=entry,stop=float(plan.stop),target=float(plan.target),
                                planned_loss=proposal['planned_loss'],budget=proposal['budget'],
                                intent_id=plan.intent_id,episode_id=signal.episode_id,target_source_ms=plan.target_source_ms,
                                decision_ms=plan.decision_ms)
                            actions['entries']+=1
                            observe(account.equity(op),i)
        if account.quantity:
            active+=1;notional=abs(account.quantity)*op;notional_sum+=notional;notional_peak=max(notional_peak,notional)
            candle=Bar(now,now+60000,*(D(str(v)) for v in (op,hi,lo,cl)))
            decision=evaluate_bar(plan,candle,active_from_ms=entered,risk_halt=halted or day_halted,
                                  strategy_close_available=now+60000 in hourly_closes)
            line=risk_line();risk_touched=(lo<=line if plan.side==1 else hi>=line)
            at_open=decision.earliest_ms==now
            if decision.reason=='ACCOUNT_RISK':
                close(i,op,'ACCOUNT_RISK')
            elif risk_touched and not at_open and (plan.side*(line-float(plan.stop))>=0):
                observe(account.equity(line),i)
                close(i,line,'ACCOUNT_RISK_TOUCH',intrabar=True,
                      ambiguous=(hi>=float(plan.target) if plan.side==1 else lo<=float(plan.target)))
            elif decision.kind in ('URGENT_EXIT_REQUIRED','EXIT_REQUIRED'):
                if decision.reference is None: raise ValueError('missing proxy price')
                observe(account.equity(float(decision.reference)),i)
                close(i,float(decision.reference),decision.reason,intrabar=not at_open,ambiguous=decision.ambiguous)
            elif decision.kind=='SCHEDULE_EXIT':
                if scheduled is None: scheduled=decision.earliest_ms
                observe(account.equity(lo if plan.side==1 else hi),i)
            elif decision.kind=='NONE':
                observe(account.equity(lo if plan.side==1 else hi),i)
            else:
                raise ValueError('unresolved execution evidence: '+decision.kind)
        observe(account.equity(cl),i);day_equity=account.equity(cl)
    preclose=account.equity(float(values[upper-1,3]))
    if account.quantity: close(upper-1,float(values[upper-1,3]),'END_EXIT',intrabar=True)
    daily.append(dict(day=str(pd.Timestamp(day,unit='D',tz='UTC').date()),equity=account.balance,halted=halted))
    verification=replay(account.events,risk.initial)
    if not math.isclose(sum(t['net_pnl'] for t in trades),account.balance-risk.initial,abs_tol=1e-7): raise ValueError('trade sum mismatch')
    return dict(metrics=dict(initial=risk.initial,final_equity=account.balance,preclose_equity=preclose,
        return_pct=(account.balance/risk.initial-1)*100,max_drawdown_pct=maxdd*100,cycles=len(trades),
        fees=account.fees,funding=account.funding,realized=account.realized,active_fraction=active/(upper-lower),
        mean_notional=notional_sum/(upper-lower),peak_notional=notional_peak,drawdown_halted=halted,
        halt_time=halt_time,warned=warned,actions=dict(actions),costs=asdict(costs),risk=asdict(risk),
        rules={k:str(v.value if hasattr(v,'value') else v) for k,v in asdict(rules).items()},
        classification='MARKET_FILL_PROXY_NOT_LIVE'),events=account.events,trades=trades,daily=daily,
        rejections=rejections,verification=verification)
