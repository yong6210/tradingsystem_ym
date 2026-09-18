"""Arrival-ordered continuous paper account. No exchange order interface.

Quotes are hypothetical fills; missed intrapoll paths remain unknown.
Funding posts on receipt against historical paper exposure, never backdates cash.
"""
from copy import deepcopy
from dataclasses import asdict
import math

from ..baseline.account import Costs
from ..baseline.risk import Risk,size_order
from .t0_signal import T0Signal
from .causal_intents import check_clock


def initial_state(signal,session,*,costs=Costs(),risk=Risk()):
    if not isinstance(session,str) or not session:raise ValueError('session required')
    return dict(version=1,session=session,sessions=[session],signal=signal.checkpoint(),
        phase='BOOTSTRAP',armed_ms=None,last_received_ns=None,last_received_utc_ns=None,
        pending=None,last_quote_time=None,cash=risk.initial,quantity=0.,average=0.,stop=None,
        entered_ms=None,realized=0.,fees=0.,funding=0.,peak=risk.initial,max_dd=0.,
        day=None,day_start=risk.initial,warned=False,halted=False,day_halted=False,
        exit_required=None,exposures=[],settlements={},quality_gaps=[],unpriced_funding_by_day={},
        observed_signals=0,eligible_intents=0,entries=0,exits=0,
        costs=asdict(costs),risk=asdict(risk))


def _observe(state,equity,now,risk):
    if not math.isfinite(equity):raise ValueError('nonfinite equity')
    day=now//86400000
    if state['day']!=day:
        state['day']=day
        state['day_start']=equity+state['unpriced_funding_by_day'].get(str(day),0.)
        state['unpriced_funding_by_day']={}
        state['day_halted']=False
    state['peak']=max(state['peak'],equity)
    dd=max(0.,1-equity/state['peak'])
    state['max_dd']=max(state['max_dd'],dd)
    if dd>=risk.warning-1e-12:state['warned']=True
    if dd>=risk.halt-1e-12 or equity<=0:state['halted']=True
    if equity<=state['day_start']*(1-risk.daily_stop)+1e-10:state['day_halted']=True


def _ledger(state,outputs,kind,now,**details):
    expected=state['risk']['initial']+state['realized']-state['fees']-state['funding']
    if not math.isclose(expected,state['cash'],rel_tol=0,abs_tol=1e-7):
        raise ValueError('paper accounting identity failed')
    outputs.append(dict(kind=kind,received_ms=now,cash=state['cash'],quantity=state['quantity'],
                        average=state['average'],**details))


def _close(state,outputs,now,reference,available,costs,reason):
    quantity=state['quantity']
    if abs(quantity)>available:
        state['exit_required']=reason
        outputs.append(dict(kind='EXIT_BLOCKED_LIQUIDITY',reason=reason,quantity=quantity,available=available))
        return False
    side=-1 if quantity>0 else 1
    price=costs.fill(reference,side);fee=abs(quantity)*price*costs.fee_bps/10000
    pnl=quantity*(price-state['average'])
    state['cash']+=pnl-fee;state['fees']+=fee;state['realized']+=pnl
    state.update(quantity=0.,average=0.,stop=None,entered_ms=None,exit_required=None)
    state['exits']+=1
    state['exposures'].append(dict(at_ms=now,quantity=0.))
    _ledger(state,outputs,'PAPER_EXIT',now,side=side,qty=abs(quantity),price=price,fee=fee,pnl=pnl,reason=reason)
    return True


def _bars(state,body,clock,now,outputs):
    if not isinstance(body,list) or not body or len(body)>1000:raise ValueError('bounded klines required')
    signal=T0Signal.restore(state['signal']);previous=None;count=0
    for row in body:
        if not isinstance(row,list) or len(row)!=12 or type(row[0]) is not int or type(row[6]) is not int:
            raise ValueError('invalid kline')
        when=row[0]
        if when%60000 or row[6]!=when+59999 or (previous is not None and when!=previous+60000):
            raise ValueError('kline interval/order')
        previous=when
        if when+60000>now-1000:continue
        found=signal.step(dict(open_ms=when,o=float(row[1]),h=float(row[2]),l=float(row[3]),c=float(row[4]),received_ms=now))
        count+=1
        if found is None or state['phase']!='OBSERVE':continue
        state['observed_signals']+=1
        if state['pending'] is not None:outputs.append(dict(kind='TARGET_SUPERSEDED',id=state['pending']['id']))
        state['pending']=None
        if found['signal_close_ms']<state['armed_ms']:
            outputs.append(dict(kind='PRE_ARM_SIGNAL_SUPPRESSED'));continue
        if now>found['scheduled_ms']+60000:
            outputs.append(dict(kind='LATE_SIGNAL_EXPIRED'));continue
        state['pending']=found|dict(id=str(found['signal_close_ms']),created_ns=clock['received_ns'],
            expires_ms=found['scheduled_ms']+60000,session=state['session'])
        state['eligible_intents']+=1
        outputs.append(dict(kind='TARGET_INTENT',**state['pending']))
    state['signal']=signal.checkpoint()
    outputs.append(dict(kind='BARS_APPLIED',count=count,phase=state['phase']))


def _quote(state,body,clock,now,outputs,costs,risk):
    if not isinstance(body,dict) or body.get('symbol')!='BTCUSDC' or type(body.get('time')) is not int:
        raise ValueError('invalid quote identity')
    bid,ask,bq,aq=(float(body[k]) for k in ('bidPrice','askPrice','bidQty','askQty'))
    if not all(math.isfinite(x) and x>0 for x in (bid,ask,bq,aq)) or bid>ask:raise ValueError('invalid quote')
    qt=body['time']
    if state['last_quote_time'] is not None and qt<state['last_quote_time']:raise ValueError('quote regression')
    state['last_quote_time']=qt
    if not -1000<=now-qt<=5000:
        outputs.append(dict(kind='STALE_QUOTE_NO_ACTION'));return
    pending=state['pending']
    if pending is not None and now>pending['expires_ms']:
        outputs.append(dict(kind='TARGET_EXPIRED',id=pending['id']))
        state['pending']=pending=None
    ready=(pending is not None and pending['session']==state['session']
           and now>=pending['earliest_observable_ms'] and qt>=pending['earliest_observable_ms']
           and clock['request_started_ns']>=pending['created_ns'])
    quantity=state['quantity'];mark=bid if quantity>=0 else ask
    equity=state['cash']+quantity*(mark-state['average'])
    _observe(state,equity,now,risk)
    outputs.append(dict(kind='PAPER_VALUATION',received_ms=now,exchange_ms=qt,equity=equity,
                        quantity=quantity,scope='OBSERVED_LIQUIDATION_SIDE_QUOTE_NO_EXIT_COST'))
    if quantity:
        side=1 if quantity>0 else -1
        reason=state['exit_required']
        if state['halted'] or state['day_halted']:reason=reason or 'risk_halt'
        if side*(mark-state['stop'])<=0:reason=reason or 'price_stop'
        if now-state['entered_ms']>=risk.maximum_hold_minutes*60000:reason=reason or 'time_exit'
        if ready and pending['side']!=side:reason=reason or ('neutral_exit' if pending['side']==0 else 'reverse_exit')
        if reason:
            if _close(state,outputs,now,mark,bq if side==1 else aq,costs,reason):
                _observe(state,state['cash'],now,risk)
                # A reversal may re-enter only on a subsequent quote request.
                if reason=='reverse_exit' and ready:
                    state['pending']['created_ns']=clock['received_ns']
                    state['pending']['earliest_observable_ms']=now+1
                else:state['pending']=None
            return
        if ready:
            outputs.append(dict(kind='HOLD_EXISTING_POSITION',side=side));state['pending']=None
        return
    if not ready:return
    if state['phase']!='OBSERVE' or state['halted'] or state['day_halted']:
        outputs.append(dict(kind='ENTRY_BLOCKED_RISK_OR_PHASE'));state['pending']=None;return
    side=pending['side']
    if side==0:
        outputs.append(dict(kind='NEUTRAL_FLAT'));state['pending']=None;return
    reference=ask if side==1 else bid
    proposal=size_order(reference,pending['close'],pending['atr'],side,state['cash'],state['warned'],costs,risk)
    if not proposal['approved']:
        outputs.append(dict(kind='ENTRY_SIZE_REJECTED',proposal=proposal));state['pending']=None;return
    qty=proposal['quantity'];available=aq if side==1 else bq
    if qty>available:
        outputs.append(dict(kind='ENTRY_BLOCKED_LIQUIDITY',qty=qty,available=available));return
    price=proposal['entry'];fee=qty*price*costs.fee_bps/10000
    state['cash']-=fee;state['fees']+=fee
    state.update(quantity=side*qty,average=price,stop=proposal['stop'],entered_ms=now,pending=None)
    state['entries']+=1
    state['exposures'].append(dict(at_ms=now,quantity=state['quantity']))
    _ledger(state,outputs,'PAPER_ENTRY',now,side=side,qty=qty,price=price,fee=fee,
            stop=proposal['stop'],planned_loss=proposal['planned_loss'],budget=proposal['budget'])
    mark=bid if side==1 else ask
    _observe(state,state['cash']+state['quantity']*(mark-price),now,risk)
    if side*(mark-state['stop'])<=0 or state['halted'] or state['day_halted']:
        state['exit_required']='entry_cost_or_gap_risk'


def _funding(state,body,now,outputs,costs):
    if not isinstance(body,dict) or body.get('symbol')!='BTCUSDC' or type(body.get('fundingTime')) is not int:
        raise ValueError('invalid settled funding identity')
    when=body['fundingTime'];rate=float(body['fundingRate']);mark=float(body['markPrice'])
    if when<0 or when>now-1000 or not math.isfinite(rate) or not math.isfinite(mark) or mark<=0:
        raise ValueError('unsettled or invalid funding')
    identity=dict(time=when,rate=rate,mark=mark)
    key=str(when)
    if key in state['settlements']:
        if state['settlements'][key]!=identity:raise ValueError('funding correction/conflict needs reconciliation')
        outputs.append(dict(kind='FUNDING_DUPLICATE',settlement_ms=when));return
    quantity=0.
    for exposure in state['exposures']:
        if abs(exposure['at_ms']-when)<=1000:raise ValueError('ambiguous settlement exposure near fill')
        if exposure['at_ms']<when:quantity=exposure['quantity']
    amount=quantity*mark*rate+abs(quantity)*mark*costs.funding_bps_8h/10000
    if not math.isfinite(amount):raise ValueError('nonfinite funding amount')
    day=now//86400000
    if state['day']!=day:
        key_day=str(day)
        state['unpriced_funding_by_day'][key_day]=state['unpriced_funding_by_day'].get(key_day,0.)+amount
    state['cash']-=amount;state['funding']+=amount;state['settlements'][key]=identity
    if state['cash']<=0:state['halted']=True
    _ledger(state,outputs,'PAPER_FUNDING',now,settlement_ms=when,settlement_quantity=quantity,
            amount=amount,mark=mark,rate=rate,stress_bps=costs.funding_bps_8h,
            posting_rule='CURRENT_RECEIPT_CASH_NO_HISTORICAL_REWRITE')
    if not state['quantity']:_observe(state,state['cash'],now,Risk(**state['risk']))


def transition(original,kind,body,clock,session):
    state=deepcopy(original);outputs=[]
    costs=Costs(**state['costs']);risk=Risk(**state['risk'])
    if kind=='BEGIN_SESSION':
        if not isinstance(session,str) or not session or session in state['sessions'] or body!={}:
            raise ValueError('new unique session required')
        now=check_clock(dict(last_received_ns=None,last_received_utc_ns=None),clock)
        if state['last_received_utc_ns'] is not None and clock['request_started_utc_ns']<state['last_received_utc_ns']:
            raise ValueError('new session wall clock precedes committed history')
        state['quality_gaps'].append(dict(from_utc_ns=state['last_received_utc_ns'],to_utc_ns=clock['received_utc_ns'],
                                          old_session=state['session'],new_session=session))
        state.update(session=session,phase='BOOTSTRAP',armed_ms=None,pending=None,last_quote_time=None)
        state['sessions'].append(session)
        if state['quantity']:state['exit_required']='restart_gap_exit'
        outputs.append(dict(kind='NEW_SESSION_REQUIRES_WARMUP',position_preserved=state['quantity']))
    else:
        if session!=state['session']:raise ValueError('wrong/old receive session')
        now=check_clock(state,clock)
        if state['last_received_utc_ns'] is not None and clock['request_started_utc_ns']<state['last_received_utc_ns']:
            raise ValueError('UTC receive order regressed')
        if kind=='ARM':
            signal=T0Signal.restore(state['signal'])
            if body!={} or state['phase']!='BOOTSTRAP' or signal.completed<80 or signal.last_open_ms is None:
                raise ValueError('invalid arm state')
            if not 0<=now-(signal.last_open_ms+60000)<=120000:raise ValueError('stale signal preparation')
            state.update(phase='OBSERVE',armed_ms=now);outputs.append(dict(kind='ARMED_PAPER_ACCOUNT'))
        elif kind=='KLINES':_bars(state,body,clock,now,outputs)
        elif kind=='QUOTE':_quote(state,body,clock,now,outputs,costs,risk)
        elif kind=='FUNDING':_funding(state,body,now,outputs,costs)
        else:raise ValueError('unsupported paper input')
    if not all(math.isfinite(state[k]) for k in ('cash','quantity','average','realized','fees','funding','peak','max_dd')):
        raise ValueError('nonfinite account state')
    state['last_received_ns']=clock['received_ns'];state['last_received_utc_ns']=clock['received_utc_ns']
    return state,outputs
