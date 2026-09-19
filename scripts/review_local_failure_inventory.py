"""Registered local-failure comparison using the existing position/cost ledger."""
import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from decimal import ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

from review_market_transition_inventory import (
    ROOT, MINUTE, load_rows, stamp, utc, PositionExample, ExampleCosts,
    alternative, net_if_closed, dec, jsonable,
)

CONFIG = ROOT/'configs/research/local_failure_inventory_trial.json'
OUT = ROOT/'reports/validation/local_failure_inventory_20260919'
MARKET = ROOT/'reports/validation/failed_break_label_20260919/review.json'


def carry(old, start):
    eligible = [(i,e) for i,e in enumerate(old['ledger']) if e['kind']=='fill' and e['time_ms']<start]
    i,e = eligible[-1]; p = PositionExample(**e['after'])
    for e in old['ledger'][i+1:]:
        if e['time_ms']>start:break
        if e['kind']=='funding':
            payment=dec(e['payment']);p=replace(p,paid_costs=p.paid_costs+payment,remaining_costs=p.remaining_costs+payment)
    state=next(s for s in old['states'] if s['time_ms']==start)
    for k in ('quantity','average','realized_gross','paid_costs'):
        assert getattr(p,k)==dec(state[k])
    # This case starts after the prior addition fill, without another outstanding intent.
    assert not any(e['time_ms']>=start and e.get('decision_ms',start)<start for e in old['ledger'] if e['kind']=='fill')
    dd=max(dec(s['drawdown']) for s in old['states'] if s['time_ms']<=start)
    return p,state,dd


def simulate(rows,funding,*,start,end,initial,initial_peak,prior_dd,account,loss_ms,target_ms,loss_fraction='0.5',target_fraction='0.5'):
    if initial.side!=-1 or initial.quantity<=0:raise ValueError('positive carried short required')
    if not 0<dec(loss_fraction)<=1 or not dec('.5')<=dec(target_fraction)<=1:raise ValueError('invalid fractions')
    costs=ExampleCosts(*(account[k] for k in ('fee','half_spread','slippage','tick','step','leverage')))
    p=initial;peak=dec(initial_peak);maximum=dec(prior_dd);extension_dd=dec(0);cash=p.starting_equity+p.realized_gross-p.paid_costs+p.quantity*p.average
    states=[];ledger=[];decisions=[];pending=None;active=None;done=set();halted=False;exposure=dec(0)
    due={};schedule_events={'loss':loss_ms,'target':target_ms};fractions={'loss':dec(loss_fraction),'target':dec(target_fraction)}
    fs=[f for f in funding if start<f['fundingTime']<=end];fi=0
    def funding_to(t):
        nonlocal p,fi,cash
        while fi<len(fs) and fs[fi]['fundingTime']<=t:
            f=fs[fi];fi+=1
            if p.quantity:
                payment=-p.quantity*dec(f['markPrice'])*dec(f['fundingRate'])
                p=replace(p,paid_costs=p.paid_costs+payment,remaining_costs=p.remaining_costs+payment);cash-=payment
                ledger.append(dict(kind='funding',time_ms=f['fundingTime'],quantity=p.quantity,payment=payment,source=f))
    def safe(position,mark):
        return (position.starting_equity+position.pnl(mark)-position.quantity*dec(mark)/costs.leverage>=dec(account['reserve_margin'])
                and position.quantity<=dec(account['maximum_total_quantity'])
                and all(net_if_closed(position,costs,dec(mark)+dec(d))>=-dec(account['total_stress_budget']) for d in account['stress_moves']))
    def restore(mark):
        if safe(p,mark):return dec(0)
        for units in range(1,int(p.quantity/costs.step)+1):
            q=units*costs.step
            after=alternative(p,costs,mark=mark,action='partial_loss_example',quantity=q,stress_moves=account['stress_moves'])['after']
            if safe(after,mark):return q
        return p.quantity
    def intent(t,q,reason):
        nonlocal pending
        if pending:ledger.append(dict(kind='replace_intent',time_ms=t,previous=deepcopy(pending),reason=reason))
        pending=dict(decision_ms=t,remaining=q,reason=reason)
        decisions.append(dict(time_ms=t,quantity=q,reason=reason,position=p))
    for b in rows:
        t=b['end_ms']
        if not start<t<=end:continue
        opening=t-MINUTE;funding_to(opening)
        if pending and opening>pending['decision_ms']:
            if pending['reason']=='capacity_restore':pending['remaining']=restore(b['open'])
            liquidity=(dec(account['assumed_liquidity_quantity'])/costs.step).to_integral_value(rounding=ROUND_FLOOR)*costs.step
            q=min(p.quantity,pending['remaining'],liquidity)
            if pending['remaining']<=0:pending=None
            elif q>=dec(account['minimum_quantity']) and q*costs.execution(b['open'],1)>=dec(account['minimum_notional']):
                before=p;f=alternative(p,costs,mark=b['open'],action='partial_loss_example',quantity=q,stress_moves=account['stress_moves'])
                p=f['after'];cash-=q*f['execution_price']+f['action_fee']
                ledger.append(dict(kind='fill',time_ms=opening,decision_ms=pending['decision_ms'],reason=pending['reason'],
                                   quantity=q,mark=b['open'],price=f['execution_price'],fee=f['action_fee'],before=before,after=p))
                pending['remaining']-=q
                # Any actual reduction after a plan starts counts toward its fixed minimum.
                if active:
                    active['remaining']=max(dec(0),active['remaining']-q)
                    if active['remaining']==0:done.add(active['kind']);active=None
                if pending['remaining']==0 or not p.quantity:pending=None
            elif not pending.get('blocked_logged'):
                ledger.append(dict(kind='blocked_execution',time_ms=opening,intent=deepcopy(pending)))
                pending['blocked_logged']=True
        funding_to(t);mark=dec(b['close']);net=p.pnl(mark);equity=p.starting_equity+net
        assert abs(cash-p.quantity*mark-equity)<dec('1e-9')
        peak=max(peak,equity);dd=peak-equity;maximum=max(maximum,dd);extension_dd=max(extension_dd,dd)
        closed=net_if_closed(p,costs,mark);free=equity-p.quantity*mark/costs.leverage;exposure+=p.quantity/60
        for kind,at in schedule_events.items():
            if at is not None and t>=at and kind not in due:due[kind]=at
        if p.quantity and (halted or max(dd,peak-(p.starting_equity+closed))>=dec(account['internal_drawdown_halt'])):
            halted=True
            if pending is None or pending['reason']!='account_halt':intent(t,p.quantity,'account_halt')
        elif p.quantity and not safe(p,mark):
            if pending is None or pending['reason'] not in ('account_halt','capacity_restore'):intent(t,restore(mark),'capacity_restore')
        elif p.quantity and pending is None:
            if active is None:
                kind=next((k for k in ('loss','target') if k in due and k not in done),None)
                if kind:
                    q=min(p.quantity,(p.quantity*fractions[kind]/costs.step).to_integral_value(rounding=ROUND_CEILING)*costs.step)
                    active=dict(kind=kind,remaining=q,base_quantity=p.quantity,required=q,activated_ms=t)
                    ledger.append(dict(kind='obligation_activated',time_ms=t,obligation=deepcopy(active),trigger_ms=due[kind]))
            if active:intent(t,active['remaining'],active['kind'])
        states.append(dict(time_ms=t,position=p,mark=mark,total_net=net,net_if_closed=closed,equity=equity,
                           free_margin_proxy=free,peak_equity=peak,drawdown=dd))
    if not states:raise ValueError('empty observation interval')
    return dict(states=states,ledger=ledger,decisions=decisions,pending=pending,active_obligation=active,
                obligations=dict(due=due,completed=sorted(done),waiting=[k for k in due if k not in done]),
                summary=dict(final=states[-1],cumulative_max_close_drawdown=maximum,extension_max_close_drawdown=extension_dd,
                             exposure_btc_hours=exposure,halted=halted),actual_orders=0,new_exposure_allowed=False)


def main():
    cfg=json.loads(CONFIG.read_text());account_path=ROOT/cfg['account_config'];account=json.loads(account_path.read_text())
    old_path=ROOT/cfg['initial_account_source'];old=json.loads(old_path.read_text());market=json.loads(MARKET.read_text())
    rows,sources=load_rows();start,end=stamp(cfg['start_utc']),stamp(cfg['end_utc'])
    initial,initial_state,dd=carry(old,start)
    last_add=next(e for e in reversed(old['decisions']) if e['time_ms']<start and e['kind']=='increase')
    level=dec(last_add['basis']['price'])
    local=next(b['end_ms'] for b in rows if start<b['end_ms']<=end and dec(b['close'])>level)
    support=next(p['time_ms'] for p in market['points'] if p['time_ms']>start and p['time_ms']%(15*MINUTE)==0 and p['support']['side']!=-1)
    target=next(b['end_ms'] for b in rows if start<b['end_ms']<=end and dec(b['low'])<=dec(cfg['target_mark']))
    funding_path=ROOT/'data/historical/btcusdc_public_20260917/funding_history.json';funding=json.loads(funding_path.read_text())
    triggers={'target_only':None,'half_at_local_failure_then_target':local,'half_at_support_loss_then_target':support}
    args=dict(start=start,end=end,initial=initial,initial_peak=initial_state['peak_equity'],prior_dd=dd,
              target_ms=target,loss_fraction=cfg['trial_loss_fraction'],target_fraction=cfg['target_reduction_fraction_of_current_quantity'])
    def group(cost):return {name:simulate(rows,funding,account=cost,loss_ms=triggers[name],**args) for name in cfg['policies']}
    policies=group(account)
    # The control must reproduce the prior actual-case hypothetical ledger, not just its final PnL.
    for s in policies['target_only']['states']:
        prior=next(x for x in old['states'] if x['time_ms']==s['time_ms'])
        for k in ('quantity','average','realized_gross','paid_costs'):assert getattr(s['position'],k)==dec(prior[k])
        for k in ('total_net','equity','free_margin_proxy','net_if_closed','peak_equity','drawdown'):assert s[k]==dec(prior[k])
    for name,result in policies.items():
        for t in sorted({local,support,target,end}|{e['time_ms']+MINUTE for e in result['ledger'] if e['kind']=='fill'}):
            prefix=simulate([b for b in rows if b['end_ms']<=t],[f for f in funding if f['fundingTime']<=t],account=account,
                            loss_ms=triggers[name] if triggers[name] is not None and triggers[name]<=t else None,
                            **dict(args,end=t,target_ms=target if target<=t else None))
            assert prefix['states']==[s for s in result['states'] if s['time_ms']<=t]
            assert prefix['decisions']==[e for e in result['decisions'] if e['time_ms']<=t]
    sensitivities={name:group(dict(account,**changes)) for name,changes in (
        ('slippage_5bp',dict(slippage='0.0005')),('liquidity_003',dict(assumed_liquidity_quantity='0.003')),
        ('no_liquidity',dict(assumed_liquidity_quantity='0')))}
    sources += [CONFIG,account_path,old_path,MARKET,funding_path,Path(__file__),ROOT/'scripts/review_market_transition_inventory.py']
    sources += [ROOT/'app/research/recovery'/x for x in ('position_alternatives.py','campaign_recovery_review.py','models.py')]
    report=dict(status='executed_development_comparison_not_approved_strategy',registered_config=cfg,
                initial_position=initial,initial_state=initial_state,prior_max_drawdown=dd,
                triggers=dict(local_failure_ms=local,support_loss_ms=support,target_ms=target,local_level=level),
                policies=policies,sensitivities=sensitivities,checks=dict(control_all_states='PASS',causal_prefix='PASS'),
                source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'review.json').write_text(json.dumps(jsonable(report),ensure_ascii=False,indent=2)+'\n')
    lines=['# 국소 근거 실패 뒤 약손절 비교','', '| 정책 | 잔량 BTC | 평가 순손익 | 가상 청산 순손익 | 누적 최대 종가 DD | 여력 대용치 |','| --- | ---: | ---: | ---: | ---: | ---: |']
    for name,r in policies.items():
        f=r['summary']['final'];lines.append(f"| {name} | {f['position'].quantity} | {f['total_net']:.6f} | {f['net_if_closed']:.6f} | {r['summary']['cumulative_max_close_drawdown']:.6f} | {f['free_margin_proxy']:.6f} |")
        for e in r['ledger']:
            if e['kind']=='fill':print(name,utc(e['time_ms']),e['reason'],str(e['quantity']),str(e['price']))
    lines+=['','| 정책 | 판단 UTC → 가정 체결 UTC | 이유 | BTC 전→후 | 체결가 |','| --- | --- | --- | --- | ---: |']
    for name,r in policies.items():
        for e in r['ledger']:
            if e['kind']=='fill':lines.append(f"| {name} | {utc(e['decision_ms'])} → {utc(e['time_ms'])} | {e['reason']} | {e['before'].quantity}→{e['after'].quantity} | {e['price']} |")
    lines+=['','잔량을 강제 청산하지 않았다. 평가손익은 미실현분 포함이며 이 구간으로 정책을 채택하지 않는다.','']
    (OUT/'review.md').write_text('\n'.join(lines));print(json.dumps(jsonable({n:r['summary'] for n,r in policies.items()}),indent=2))


if __name__=='__main__':main()
