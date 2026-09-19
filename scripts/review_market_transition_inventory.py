"""Continue the existing hypothetical inventory through a structural transition."""
from copy import deepcopy
from dataclasses import replace
from decimal import ROUND_CEILING,ROUND_FLOOR
import hashlib
import json
from pathlib import Path

from review_market_judgment_regimes import ROOT,MINUTE,DAY,load_rows,prepare,snapshot,stable_context,utc,stamp
from review_market_basis_revision import revise_basis,current_support,with_bounds
from review_market_direction_continuity import advance,anchor_bars
from app.research.recovery.position_alternatives import PositionExample,ExampleCosts,alternative
from app.research.recovery.campaign_recovery_review import net_if_closed
from app.research.recovery.models import dec,jsonable

CONFIG=ROOT/'configs/research/transition_inventory_trial.json'
DOC=ROOT/'docs/research/MARKET_TRANSITION_INVENTORY_TRIAL.md'
OUT=ROOT/'reports/validation/market_transition_inventory_20260919'
ACCOUNT=ROOT/'reports/validation/first_candidate_account_20260919/review.json'
BASIS=ROOT/'reports/validation/market_basis_revision_20260919/review.json'


def restore_position(old):
    if old['pending'] is not None:raise ValueError('unresolved prior execution state')
    index=max(i for i,e in enumerate(old['ledger']) if e['kind']=='fill')
    p=PositionExample(**old['ledger'][index]['after'])
    for e in old['ledger'][index+1:]:
        if e['kind']!='funding':raise ValueError('unsupported carry event')
        p=replace(p,paid_costs=p.paid_costs+dec(e['payment']),remaining_costs=p.remaining_costs+dec(e['payment']))
    last=old['summary']['final']
    for k in ('quantity','average','realized_gross','paid_costs'):
        assert getattr(p,k)==dec(last[k])
    return p


def market_trace(rows,cfg,seed,structure_cfg):
    start,end=stamp(cfg['start_utc']),stamp(cfg['end_utc']);reference=stamp(cfg['history_reference_utc'])
    prepared=[prepare(rows,reference-days*DAY,end,structure_cfg) for days in structure_cfg['history_days']]
    assert seed['last_ms']==start
    def run(prepared,times):
        state=deepcopy(seed);points=[];events=[];failed=None;opposite=None
        for t in times:
            views=[snapshot(p,t) for p in prepared];context=stable_context(views)
            state,e=advance(state,t=t,context=context,bars=anchor_bars(prepared[-1],state,t))
            if e:
                events.append(e)
                if e['kind']=='basis_invalidated' and failed is None:failed=t
            state,e=revise_basis(state,views,t)
            if e:events.append(e)
            support=current_support(state,with_bounds(views,prepared,state,t),t)
            if failed is not None and opposite is None and support['side']==1 and state['root']['candidate']['formed_ms']>failed:
                opposite=t
            points.append(dict(time_ms=t,utc=utc(t),context=context,views=views,state=deepcopy(state),support=support))
        return dict(points=points,events=events,failure_ms=failed,opposition_ms=opposite)
    times=list(range((start//(15*MINUTE)+1)*15*MINUTE,end+1,15*MINUTE))
    result=run(prepared,times)
    for t in sorted({x for x in (result['failure_ms'],result['opposition_ms'],times[-1]) if x is not None}):
        trunc=[prepare([b for b in rows if b['end_ms']<=t],reference-days*DAY,t,structure_cfg) for days in structure_cfg['history_days']]
        prefix=run(trunc,[x for x in times if x<=t])
        assert prefix['points']==[p for p in result['points'] if p['time_ms']<=t]
        assert prefix['events']==[e for e in result['events'] if e['time_ms']<=t]
    result['prefix_rebuild']='PASS';return result


def simulate(rows,funding,*,start,end,initial,initial_peak,prior_max_dd,account,policy,failure_ms,opposition_ms,half_fraction="0.5"):
    if policy not in ('exit_on_basis_failure','half_on_failure_rest_on_opposition','exit_on_opposition'):raise ValueError('unknown policy')
    if opposition_ms is not None and (failure_ms is None or opposition_ms<=failure_ms):raise ValueError('opposition must follow basis failure')
    if initial.side!=-1 or initial.quantity<=0:raise ValueError('existing short inventory required')
    if not 0<dec(half_fraction)<=1:raise ValueError('invalid trial reduction fraction')
    initial_mark=next(b['close'] for b in rows if b['end_ms']==start)
    initial_net=initial.pnl(initial_mark)
    costs=ExampleCosts(*(account[k] for k in ('fee','half_spread','slippage','tick','step','leverage')))
    p=initial;peak=dec(initial_peak);max_dd=dec(prior_max_dd);extension_dd=dec(0);worst_high_dd=dec(0)
    cash=p.starting_equity+p.realized_gross-p.paid_costs+p.quantity*p.average
    pending=None;ledger=[];decisions=[];states=[];halted=False;failure_processed=False;opposition_processed=False;fees=dec(0);paid_funding=dec(0);exposure_minutes=0;quantity_minutes=dec(0)
    fs=[f for f in funding if start<f['fundingTime']<=end];fi=0
    def fund_until(t):
        nonlocal p,cash,fi,paid_funding
        while fi<len(fs) and fs[fi]['fundingTime']<=t:
            f=fs[fi];fi+=1;payment=p.side*p.quantity*dec(f['markPrice'])*dec(f['fundingRate'])
            if p.quantity:
                p=replace(p,paid_costs=p.paid_costs+payment,remaining_costs=p.remaining_costs+payment)
                cash-=payment;paid_funding+=payment
                ledger.append(dict(kind='funding',time_ms=f['fundingTime'],quantity=p.quantity,payment=payment,source=f))
    def limits(position,mark):
        free=position.starting_equity+position.pnl(mark)-position.quantity*dec(mark)/costs.leverage
        stress=[net_if_closed(position,costs,dec(mark)-position.side*dec(d)) for d in account['stress_moves']]
        return free>=dec(account['reserve_margin']) and position.quantity<=dec(account['maximum_total_quantity']) and min(stress)>=-dec(account['total_stress_budget'])
    def restore_qty(mark):
        if limits(p,mark):return dec(0)
        for units in range(1,int(p.quantity/costs.step)+1):
            q=units*costs.step
            after=alternative(p,costs,mark=mark,action='partial_loss_example',quantity=q,stress_moves=account['stress_moves'])['after']
            if limits(after,mark):return q
        return p.quantity
    def schedule(t,quantity,reason):
        nonlocal pending
        if quantity<=0:return
        if pending:ledger.append(dict(kind='replace_intent',time_ms=t,previous=deepcopy(pending),reason=reason))
        pending=dict(decision_ms=t,remaining=quantity,reason=reason)
        decisions.append(dict(time_ms=t,quantity=quantity,reason=reason,position=deepcopy(p)))
    for b in rows:
        t=b['end_ms']
        if not start<t<=end:continue
        opening=t-MINUTE;fund_until(opening)
        if pending and opening>pending['decision_ms']:
            if pending['reason']=='capacity_restore':pending['remaining']=restore_qty(b['open'])
            liquid=(dec(account['assumed_liquidity_quantity'])/costs.step).to_integral_value(rounding=ROUND_FLOOR)*costs.step
            q=min(pending['remaining'],p.quantity,liquid)
            if pending['remaining']<=0:pending=None
            elif q>=dec(account['minimum_quantity']) and q*costs.execution(b['open'],1)>=dec(account['minimum_notional']):
                before=p;fill=alternative(p,costs,mark=b['open'],action='partial_loss_example',quantity=q,stress_moves=account['stress_moves'])
                p=fill['after'];fees+=fill['action_fee'];cash-=q*fill['execution_price']+fill['action_fee']
                ledger.append(dict(kind='fill',time_ms=opening,decision_ms=pending['decision_ms'],reason=pending['reason'],quantity=q,
                    mark=b['open'],price=fill['execution_price'],fee=fill['action_fee'],before=before,after=p))
                pending['remaining']-=q
                if pending['remaining']<=0 or not p.quantity:pending=None
            elif not pending.get('blocked_logged'):
                ledger.append(dict(kind='blocked_execution',time_ms=opening,reason='insufficient_assumed_liquidity_or_minimum_size',intent=deepcopy(pending)))
                pending['blocked_logged']=True
        if p.quantity:
            exposure_minutes+=1;quantity_minutes+=p.quantity
        fund_until(t);mark=dec(b['close']);equity=p.starting_equity+p.pnl(mark)
        assert abs(cash-p.quantity*mark-equity)<dec('0.000000001')
        peak=max(peak,equity);dd=peak-equity;max_dd=max(max_dd,dd);extension_dd=max(extension_dd,dd)
        worst_high_dd=max(worst_high_dd,peak-(p.starting_equity+p.pnl(b['high'])))
        closed=net_if_closed(p,costs,mark);free=equity-p.quantity*mark/costs.leverage
        if p.quantity and max(dd,peak-(p.starting_equity+closed))>=dec(account['internal_drawdown_halt']):
            halted=True
            if pending is None or pending['reason']!='account_halt':schedule(t,p.quantity,'account_halt')
        elif p.quantity and not limits(p,mark):
            if pending is None or pending['reason'] not in ('account_halt','capacity_restore'):schedule(t,restore_qty(mark),'capacity_restore')
        elif p.quantity and (pending is None or pending['reason'] not in ('account_halt','capacity_restore')):
            if opposition_ms is not None and t>=opposition_ms and not opposition_processed and policy in ('half_on_failure_rest_on_opposition','exit_on_opposition'):
                schedule(t,p.quantity,'opposition_after_failure_exit_trial');opposition_processed=True;failure_processed=True
            elif failure_ms is not None and t>=failure_ms and not failure_processed:
                if policy=='exit_on_basis_failure':schedule(t,p.quantity,'basis_failure_full_exit_trial');failure_processed=True
                elif policy=='half_on_failure_rest_on_opposition':
                    q=(p.quantity*dec(half_fraction)/costs.step).to_integral_value(rounding=ROUND_CEILING)*costs.step
                    schedule(t,min(q,p.quantity),'basis_failure_half_loss_trial');failure_processed=True
        states.append(dict(time_ms=t,position=p,mark=mark,total_net=p.pnl(mark),net_if_closed=closed,equity=equity,free_margin_proxy=free,peak_equity=peak,drawdown=dd))
    return dict(policy=policy,ledger=ledger,decisions=decisions,states=states,pending=pending,
        summary=dict(final=states[-1],extension_fees=fees,extension_funding_paid=paid_funding,extension_net_change=states[-1]['total_net']-initial_net,
            cumulative_max_close_drawdown=max_dd,extension_max_close_drawdown=extension_dd,
            extension_adverse_high_drawdown=worst_high_dd,exposure_minutes=exposure_minutes,exposure_btc_hours=quantity_minutes/60,halted=halted,actual_orders=0),
        independent_cash_audit='PASS',new_exposure_allowed=False)


def render(r):
    lines=['# 8월 17일 전환 후보와 기존 숏 물량','',
        '이전 계좌를 이월한 세 시험 정책의 비교다. 실제 주문·전략 채택·반대 신규 진입은 없다. 절반 약손절은 시험값이며 추가 후 되돌림 절반 원칙과 구분한다.','',
        '| 정책 | 최종 BTC | 누적 순손익 | 연장 구간 수수료 | 연장 펀딩 지급 | 기존 고점 대비 최대 종가 DD | 노출 시간(분) / BTC·시간 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name,a in r['policies'].items():
        s=a['summary'];f=s['final'];lines.append(f"| {name} | {f['position'].quantity} | {f['total_net']:.6f} | {s['extension_fees']:.6f} | {s['extension_funding_paid']:.6f} | {s['extension_max_close_drawdown']:.6f} | {s['exposure_minutes']} / {s['exposure_btc_hours']} |")
    lines+=['','## 시장 근거와 행동 시각','','기준 무효화: '+str(utc(r['market']['failure_ms']))+' / 별도 반대 후보: '+str(utc(r['market']['opposition_ms'])),
            '완료 시각에 판단하고 엄격히 뒤의 시가에서 체결을 가정했다. 기존 물량 종료는 롱 진입 승인이 아니다.','']
    for name,a in r['policies'].items():
        lines+=['### '+name,'','| 판단 UTC → 체결 UTC | 이유 | 수량 전→후 | 체결가 | 누적 실현총손익 | 누적 비용 |','| --- | --- | --- | ---: | ---: | ---: |']
        for e in a['ledger']:
            if e['kind']=='fill':lines.append(f"| {utc(e['decision_ms'])} → {utc(e['time_ms'])} | {e['reason']} | {e['before'].quantity}→{e['after'].quantity} | {e['price']} | {e['after'].realized_gross} | {e['after'].paid_costs} |")
    lines+=['','## 비용·유동성 대조','','| 대조 | 정책 | 최종 BTC | 평가 순손익 | 미체결 의도 |','| --- | --- | ---: | ---: | --- |']
    for name,group in r['sensitivities'].items():
        for policy,a in group.items():
            f=a['summary']['final'];lines.append(f"| {name} | {policy} | {f['position'].quantity} | {f['total_net']:.6f} | {a['pending'] is not None} |")
    lines+=['','이 구간의 결과로 정책을 고르지 않는다. 종료 정책·약손절 비율·실제 주된 전환의 충분성은 아직 시험 가정이다. 실제 거래소 호가·대사·유지증거금·운영비는 미검증이다. 4단계 미완료, 5·6단계 보류.','']
    return '\n'.join(lines)


def main():
    cfg=json.loads(CONFIG.read_text());account_path=ROOT/cfg['account_config'];account=json.loads(account_path.read_text())
    old=json.loads(ACCOUNT.read_text());basis=json.loads(BASIS.read_text());initial=restore_position(old)
    start,end=stamp(cfg['start_utc']),stamp(cfg['end_utc']);assert old['summary']['final']['time_ms']==start
    seed=next(c for c in basis['cases'] if c['label']=='original_nine')['points'][-1]['updated_only']
    rows,sources=load_rows();funding_path=ROOT/'data/historical/btcusdc_public_20260917/funding_history.json';funding=json.loads(funding_path.read_text())
    structure_path=ROOT/'configs/research/market_judgment_regime_review.json';structure=json.loads(structure_path.read_text())
    market=market_trace(rows,cfg,seed,structure)
    assert market['failure_ms'] is not None and market['opposition_ms'] is not None
    args=dict(start=start,end=end,initial=initial,initial_peak=old['summary']['final']['peak_equity'],
        prior_max_dd=old['summary']['maximum_close_drawdown'],half_fraction=cfg['half_loss_fraction'],failure_ms=market['failure_ms'],opposition_ms=market['opposition_ms'])
    policies={p:simulate(rows,funding,account=account,policy=p,**args) for p in cfg['policies']}
    for p,a in policies.items():
        for t in sorted({x['time_ms'] for x in a['decisions']}|{e['time_ms']+MINUTE for e in a['ledger'] if e['kind']=='fill'}):
            prefix=simulate([b for b in rows if b['end_ms']<=t],[f for f in funding if f['fundingTime']<=t],account=account,policy=p,**dict(args,end=t,
                failure_ms=market['failure_ms'] if market['failure_ms']<=t else None,opposition_ms=market['opposition_ms'] if market['opposition_ms']<=t else None))
            assert prefix['ledger']==[e for e in a['ledger'] if e['time_ms']<t or (e['kind'] in ('funding','replace_intent') and e['time_ms']==t)]
            assert prefix['decisions']==[x for x in a['decisions'] if x['time_ms']<=t]
    sensitivities={}
    for name,changes in [('slippage_5bp',dict(slippage='0.0005')),('liquidity_003',dict(assumed_liquidity_quantity='0.003')),('no_liquidity',dict(assumed_liquidity_quantity='0'))]:
        sensitivities[name]={p:simulate(rows,funding,account=dict(account,**changes),policy=p,**args) for p in cfg['policies']}
    result=dict(status='conditional_inventory_policy_comparison',config=cfg,initial_position=initial,market=market,
        policies=policies,sensitivities=sensitivities,prefix_invariance='PASS',orders_generated=0,new_exposure_allowed=False)
    sources += [CONFIG,DOC,ACCOUNT,BASIS,account_path,structure_path,funding_path,Path(__file__),
        ROOT/'scripts/review_market_basis_revision.py',ROOT/'scripts/review_market_direction_continuity.py',ROOT/'scripts/review_market_judgment_regimes.py']
    sources += [ROOT/'app/research/recovery'/p for p in ('position_alternatives.py','campaign_recovery_review.py','models.py','protected_structure.py','structure_review.py')]
    result['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'review.json').write_text(json.dumps(jsonable(result),ensure_ascii=False,indent=2)+'\n');(OUT/'review.md').write_text(render(result))
    print(json.dumps(jsonable({p:a['summary'] for p,a in policies.items()}),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
