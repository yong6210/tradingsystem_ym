"""Conditional case worksheet, using existing sizing and inventory arithmetic.

No transport or production strategy entry point. Rules are declared in
FIRST_CANDIDATE_CASE_TRIAL.md before observing this case's continuation.
"""
import csv
import hashlib
import io
import json
from dataclasses import replace
from decimal import ROUND_CEILING
from pathlib import Path
from zipfile import ZipFile

from replay_cycling_trial_v1 import ROOT, ARCHIVE, stamp
from review_main_direction_opposition import NEW, utc
from app.research.recovery.models import dec, jsonable
from app.research.recovery.position_alternatives import PositionExample, ExampleCosts, alternative
from app.research.recovery.cycling_admission import Capacity
from app.research.recovery.recovery_capacity_review import review_capacity
from app.research.recovery.campaign_recovery_review import net_if_closed
from app.research.recovery.round_trip_review import round_trip
from app.research.recovery.structure_review import completed_bars, observe_structure
from app.research.recovery.protected_structure import protected_structure

CONFIG=ROOT/'configs/research/first_candidate_case_trial.json'
CANDIDATE=ROOT/'reports/validation/main_direction_opposition_20260919/review.json'
FUNDING=ROOT/'data/historical/btcusdc_public_20260917/funding_history.json'


def contacts(rows,end):
    """Only confirmed landmark fields enter the sequential minute state."""
    points=observe_structure(completed_bars(rows,end,15))['pivots']
    pending=sorted([{k:p[k] for k in ('id','price','pivot_bar_end_ms','available_ms')}
                    for p in points if p['kind']=='high'],key=lambda p:p['available_ms'])
    active=[];cursor=0;result={}
    for b in rows:
        t=b['end_ms']
        if t>end:break
        for p in active:
            if p['done']:continue
            if b['close']>p['price']:p['done']=True;continue
            if p['departed_ms'] is None:
                if b['high']<p['price']:p['departed_ms']=t
                continue
            if b['low']<=p['price']<=b['high']:
                p['done']=True
                if b['close']<p['price']:
                    result.setdefault(t,[]).append({k:v for k,v in p.items() if k!='done'})
        while cursor<len(pending) and pending[cursor]['available_ms']<=t:
            active.append(dict(pending[cursor],done=False,departed_ms=None));cursor+=1
    return result


def replay(rows,funding,candidate,cfg,end=None):
    start=candidate['decision_ms'];end=end or stamp(cfg['end_utc'])
    rows=[b for b in rows if b['end_ms']<=end]
    if not rows or rows[-1]['end_ms']!=end:raise ValueError('missing terminal candle')
    for left,right in zip(rows,rows[1:]):
        if right['end_ms']-left['end_ms']!=60000:raise ValueError('missing or duplicate minute')
    if not funding or funding[0]['fundingTime']>start or funding[-1]['fundingTime']<end:
        raise ValueError('funding source does not span the case')
    costs=ExampleCosts(*(cfg[k] for k in ('fee','half_spread','slippage','tick','step','leverage')))
    equity=dec(cfg['starting_equity']);target=dec(cfg['target_mark']);step=costs.step
    position=PositionExample(-1,0,None,0,0,0,equity)
    reactions=contacts(rows,end);ledger=[];decisions=[];states=[];pending=None
    funding_rows=[f for f in funding if start<f['fundingTime']<=end];fi=0
    cash=equity;peak=equity;max_dd=dec(0);worst_bar_dd=dec(0);max_qty=dec(0)
    initial_qty=None;growth=0;reduced_growth=-1;halted=False;hourly={};last_direction=None
    total_funding=dec(0);total_fees=dec(0);last_basis=None;basis_failed=False;last_growth_decision=None

    def direction_at(t):
        hour=t//3600000*3600000
        if hour not in hourly:
            hourly[hour]=protected_structure(completed_bars(rows,t,60),confirmation_mode=NEW)['candidate']
        return hourly[hour]

    def position_state(mark):
        net=position.pnl(mark)
        return dict(quantity=position.quantity,average=position.average,realized_gross=position.realized_gross,
            paid_costs=position.paid_costs,total_net=net,equity=equity+net,
            free_margin_proxy=equity+net-position.quantity*dec(mark)/costs.leverage,
            net_if_closed=net_if_closed(position,costs,mark))

    def fund_until(t):
        nonlocal fi,position,cash,total_funding
        while fi<len(funding_rows) and funding_rows[fi]['fundingTime']<=t:
            f=funding_rows[fi];fi+=1
            payment=position.side*position.quantity*dec(f['markPrice'])*dec(f['fundingRate'])
            position=replace(position,paid_costs=position.paid_costs+payment,remaining_costs=position.remaining_costs+payment)
            cash-=payment;total_funding+=payment
            ledger.append(dict(kind='funding',time_ms=f['fundingTime'],quantity=position.quantity,payment=payment,source=f))

    def capacity(mark,t,initial,requested):
        cap=Capacity(t,max(dec(0),position_state(mark)['free_margin_proxy']),cfg['reserve_margin'],
                     dec(mark)/costs.leverage,cfg['maximum_total_quantity'],
                     cfg['initial_stress_budget'] if initial else cfg['total_stress_budget'],cfg['stress_moves'])
        return review_capacity(position,costs,mark=mark,quote_ms=t,capacity=cap,requested=requested,
            liquidity_qty=cfg['assumed_liquidity_quantity'],minimum_quantity=cfg['minimum_quantity'],
            minimum_notional=cfg['minimum_notional'],now_ms=t,max_age_ms=0)

    def within_limits(p,mark):
        free=equity+p.pnl(mark)-p.quantity*dec(mark)/costs.leverage
        return (free>=dec(cfg['reserve_margin']) and p.quantity<=dec(cfg['maximum_total_quantity']) and
                all(net_if_closed(p,costs,dec(mark)+dec(move))>=-dec(cfg['total_stress_budget']) for move in cfg['stress_moves']))

    def restore_quantity(mark):
        for units in range(1,int(position.quantity/step)+1):
            q=units*step
            if q<dec(cfg['minimum_quantity']) or q*costs.execution(mark,1)<dec(cfg['minimum_notional']):continue
            after=alternative(position,costs,mark=mark,action='partial_loss_example',quantity=q,stress_moves=cfg['stress_moves'])['after']
            if within_limits(after,mark):return q
        return position.quantity

    def intent(t,kind,quantity,reason,basis=None,review=None):
        nonlocal pending
        row=dict(time_ms=t,kind=kind,quantity=quantity,reason=reason,basis=basis,capacity=review,
                 before=position_state(current['close']))
        decisions.append(row);pending=row

    for current in rows:
        t=current['end_ms']
        if t<start:continue
        opening=t-60000
        fund_until(opening)
        if pending and opening>pending['time_ms']:
            plan=pending;pending=None;mark=dec(current['open']);q=dec(plan['quantity'])
            reason=None
            if plan['kind']=='increase':
                initial=initial_qty is None
                cap=capacity(mark,opening,initial,q)
                q=cap['capacity_quantity'] or dec(0)
                fresh_direction=direction_at(opening)
                if fresh_direction is None or fresh_direction['side']!=-1 or fresh_direction['status']!='active':
                    reason='opening_direction_not_active_short'
                elif mark>dec(plan['basis']['price']):reason='opening_above_local_resistance'
                elif q<=0:reason='opening_capacity_insufficient'
                elif round_trip(costs,side=-1,quantity=q,entry_mark=mark,exit_mark=target)['net']<=0:
                    reason='opening_below_economic_minimum_sell_price'
                if reason:
                    ledger.append(dict(kind='cancel',time_ms=opening,decision_ms=plan['time_ms'],reason=reason))
                else:
                    # Required fill floor derives from the predeclared target and fees.
                    exit_fill=costs.execution(target,1)
                    floor=(exit_fill*(1+costs.fee)/(1-costs.fee)/costs.tick).to_integral_value(rounding=ROUND_CEILING)*costs.tick
                    assert costs.execution(mark,-1)>=floor
            elif plan['kind']=='partial_loss_example':
                q=restore_quantity(mark) if not within_limits(position,mark) else dec(0)
                if not q:reason='limits_recovered_before_execution'
            else:
                q=min(q,position.quantity)
            if not reason and q>0:
                before=position
                action='partial_loss_example' if plan['kind']=='halt_exit' else plan['kind']
                result=alternative(position,costs,mark=mark,action=action,quantity=q,stress_moves=cfg['stress_moves'])
                position=result['after'];fee=result['action_fee'];price=result['execution_price']
                total_fees+=fee
                cash+=(q*price if plan['kind']=='increase' else -q*price)-fee
                if plan['kind']=='increase':
                    if initial_qty is None:initial_qty=q
                    growth+=1
                    last_basis=plan['basis'];basis_failed=False
                    last_growth_decision=plan['time_ms']
                elif plan['kind']=='retracement_reduce':reduced_growth=growth
                ledger.append(dict(kind='fill',time_ms=opening,decision_ms=plan['time_ms'],action=plan['kind'],
                    reason=plan['reason'],quantity=q,price=price,fee=fee,before=before,after=position,mark=mark))
        fund_until(t)
        mark=dec(current['close']);state=position_state(mark)
        assert abs(cash-position.quantity*mark-state['equity'])<dec('0.00000001')
        peak=max(peak,state['equity']);dd=peak-state['equity'];max_dd=max(max_dd,dd)
        worst_bar_dd=max(worst_bar_dd,peak-(equity+position.pnl(current['high'])))
        max_qty=max(max_qty,position.quantity)
        direction=direction_at(t)
        active_short=direction is not None and direction['side']==-1 and direction['status']=='active'
        signature=None if direction is None else (direction['side'],direction['status'],direction['formed_ms'])
        if signature!=last_direction:
            decisions.append(dict(time_ms=t,kind='direction_review',candidate=direction,
                reason='case_short_structure_active' if active_short else 'no_new_exposure_existing_inventory_market_exit_unresolved'))
            last_direction=signature
        if position.quantity and last_basis and not basis_failed and mark>dec(last_basis['price']):
            decisions.append(dict(time_ms=t,kind='local_basis_failed',basis=last_basis,
                reason='block_basis_reuse_not_automatic_main_reversal_or_full_exit',state=state))
            basis_failed=True
        if not pending:
            if position.quantity and (dd>=dec(cfg['internal_drawdown_halt']) or peak-(equity+state['net_if_closed'])>=dec(cfg['internal_drawdown_halt'])):
                halted=True;intent(t,'partial_loss_example',position.quantity,'account_drawdown_halt')
                # Halt is a full close, unlike minimum limit restoration.
                pending['kind']='halt_exit'
            elif position.quantity and not within_limits(position,mark):
                intent(t,'partial_loss_example',restore_quantity(mark),'restore_explicit_capacity_limits')
            elif position.quantity and growth!=reduced_growth and dec(current['low'])<=target:
                q=(position.quantity*dec(cfg['reduction_fraction'])/step).to_integral_value(rounding=ROUND_CEILING)*step
                if q>=dec(cfg['minimum_quantity']) and q*costs.execution(mark,1)>=dec(cfg['minimum_notional']):
                    intent(t,'retracement_reduce',q,'target_touched_or_passed_total_quantity_half')
            elif not halted and t==start:
                review=capacity(mark,t,True,cfg['maximum_total_quantity']);q=review['capacity_quantity'] or dec(0)
                if active_short and q>0:
                    intent(t,'increase',q,'frozen_first_candidate',candidate['marker'],review)
                else:decisions.append(dict(time_ms=t,kind='entry_rejected',capacity=review))
            elif not halted and position.quantity and t in reactions:
                available=reactions[t]
                fresh=[p for p in available if min(p['pivot_bar_end_ms'],p['available_ms'])>last_growth_decision]
                basis=(fresh or available)[0] if cfg.get('require_post_growth_landmark') else available[0]
                reason=None
                if cfg.get('require_post_growth_landmark') and not fresh:reason='historical_landmark_not_new_after_last_growth'
                elif not active_short:reason='direction_unresolved'
                elif mark<=position.average:reason='no_adverse_price_for_this_addition_trial'
                elif round_trip(costs,side=-1,quantity=initial_qty,entry_mark=mark,exit_mark=target)['net']<=0:reason='no_positive_marginal_room'
                if reason:decisions.append(dict(time_ms=t,kind='add_rejected',reason=reason,basis=basis))
                else:
                    review=capacity(mark,t,False,initial_qty);q=review['capacity_quantity'] or dec(0)
                    if q>0:intent(t,'increase',q,'new_separate_reaction_with_capacity',basis,review)
                    else:decisions.append(dict(time_ms=t,kind='add_rejected',reason='no_capacity',capacity=review,basis=basis))
        states.append(dict(time_ms=t,**state,peak_equity=peak,drawdown=dd))
    return dict(status='conditional_case_not_strategy_validation',config=cfg,decisions=decisions,ledger=ledger,states=states,
        pending=pending,summary=dict(initial_quantity=initial_qty,maximum_quantity=max_qty,final=states[-1],
            fees=total_fees,funding_paid=total_funding,maximum_close_drawdown=max_dd,worst_bar_high_drawdown=worst_bar_dd,
            halted=halted,operating_cost=None,actual_orders=0),independent_cash_audit='PASS')


def main():
    cfg=json.loads(CONFIG.read_text());candidate=json.loads(CANDIDATE.read_text())['entry_scan']['first_candidate']
    if candidate['decision_ms']!=stamp(cfg['candidate_utc']):raise ValueError('candidate mismatch')
    raw=ARCHIVE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ARCHIVE.with_name(ARCHIVE.name+'.CHECKSUM').read_text().split()[0]:raise ValueError('archive checksum')
    rows=[]
    with ZipFile(io.BytesIO(raw)) as z,z.open(z.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            rows.append(dict(end_ms=int(r['open_time'])+60000,**{k:float(r[k]) for k in ('open','high','low','close')}))
    funding=json.loads(FUNDING.read_text())
    result=replay(rows,funding,candidate,cfg)
    comparisons={}
    variants={
        'pre_freshness_failure':dict(require_post_growth_landmark=False),
        'fee_4bp':dict(fee='0.0004'),
        'slippage_5bp':dict(slippage='0.0005'),
        'liquidity_003':dict(assumed_liquidity_quantity='0.003'),
    }
    for name,changes in variants.items():
        scenario=replay(rows,funding,candidate,dict(cfg,**changes))
        comparisons[name]=dict(config=scenario['config'],summary=scenario['summary'],ledger=scenario['ledger'],
                               decisions=scenario['decisions'],independent_cash_audit=scenario['independent_cash_audit'])
    result['comparisons']=comparisons
    # Recompute at every fill decision cutoff; later candles must be irrelevant.
    for t in sorted({r['time_ms'] for r in result['decisions'] if r['kind'] in ('increase','retracement_reduce','partial_loss_example','halt_exit')}):
        prefix=replay(rows,funding,candidate,cfg,end=t)
        assert prefix['decisions']==[r for r in result['decisions'] if r['time_ms']<=t]
        assert prefix['ledger']==[r for r in result['ledger'] if r['time_ms']<t or (r['kind']=='funding' and r['time_ms']==t)]
    result['prefix_invariance']='PASS'
    sources=[ARCHIVE,FUNDING,CANDIDATE,CONFIG,Path(__file__),ROOT/'docs/research/FIRST_CANDIDATE_CASE_TRIAL.md',
             ROOT/'configs/research/account_cost_context_20260919.json',ROOT/'configs/research/user_profit_risk_context_20260919.json']
    sources.extend((ROOT/'app/research/recovery'/name) for name in ('position_alternatives.py','recovery_capacity_review.py','campaign_recovery_review.py','round_trip_review.py','structure_review.py','protected_structure.py','models.py','cycling_admission.py'))
    result['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    out=ROOT/'reports/validation/first_candidate_account_20260919';out.mkdir(parents=True,exist_ok=True)
    (out/'review.json').write_text(json.dumps(jsonable(result),ensure_ascii=False,indent=2)+'\n')
    (out/'review.md').write_text(render(result))
    print(json.dumps(jsonable(result['summary']),ensure_ascii=False,indent=2))


def render(result):
    s=result['summary'];cfg=result['config']
    lines=['# 첫 후보에서 진입·추가·축소까지 — 조건부 계좌 검토','',
        'BTCUSDC 2026-08-15 18:14~08-17 00:01 UTC, 기존 개발 자료다. 실제 주문은 없으며 계좌 수량·체결·위험 한도는 시험 가정이다. 사용자 기록의 자금 1,000 USDC와 테이커 2.5bp를 적용했지만 당시 실제 수수료율·호가·계좌 상태는 확인되지 않았다.',
        '기존 0.1 BTC·10,000 USDC 사례는 설명용이다. 이번 최초 수량은 초기 스트레스 예산 20 USDC, 이후 총 예산 40 USDC·예비 증거금 300 USDC에서 산출했다. 2~3천 달러 역행은 스트레스 계산이며 가격 손절이 아니다.', '',
        '## 판단과 모의 체결을 시간순으로 연결','',
        '| 판단 UTC → 체결 UTC | 행동과 이유 | BTC 전→후 | 체결가 / 이후 평단 | 누적 실현총손익 | 누적 비용(펀딩 포함) | 체결 시가 기준 여력 대용치 |',
        '| --- | --- | --- | --- | ---: | ---: | ---: |']
    names={'frozen_first_candidate':'최초 숏 진입','new_separate_reaction_with_capacity':'새 구조 반응에서 추가',
           'target_touched_or_passed_total_quantity_half':'목표 확인 후 총량 절반 축소',
           'restore_explicit_capacity_limits':'한도 복구 약손절','account_drawdown_halt':'계좌 중단 전량 종료'}
    for row in result['ledger']:
        if row['kind']!='fill':continue
        p=row['after'];free=p.starting_equity+p.pnl(row['mark'])-p.quantity*row['mark']/dec(cfg['leverage'])
        avg='없음' if p.average is None else f'{p.average:.2f}'
        description=names[row['reason']]
        decision=next(d for d in result['decisions'] if d['time_ms']==row['decision_ms'] and d['kind']==row['action'])
        if decision.get('basis'):
            basis=decision['basis'];description+=f"; 고점 {basis['price']}, 확인 {utc(basis['available_ms'])}"
        lines.append(f"| {utc(row['decision_ms'])} → {utc(row['time_ms'])} | {description} | {row['before'].quantity}→{p.quantity} | {row['price']:.1f} / {avg} | {p.realized_gross:.6f} | {p.paid_costs:.6f} | {free:.4f} |")
    lines += ['', '축소는 목표 가격에 체결됐다고 가정하지 않았다. 결정과 동일 시각의 시가도 사용하지 않고 그보다 엄격히 뒤인 분봉 시가에 비용을 적용했다. 잔량을 다음 시점으로 이월하며 같은 증가 주기에 축소를 반복하지 않는다.', '',
        '## 주된 방향·반대 근거·재판단','',
        '| UTC | 결정 | 근거 / 재판단 의미 |','| --- | --- | --- |']
    for d in result['decisions']:
        if d['kind']=='direction_review':
            c=d['candidate'];basis='없음' if c is None else f"방향 {c['side']}, {c['status']}, 반응가격 {c['protected']['price']}"
            note=basis+'; 방향이 무효면 새 노출 보류. 기존 잔량 시장 종료는 미결이며 계좌 한도·등록 목표를 따로 심사.'
        elif d['kind']=='local_basis_failed':
            note=f"국소 고점 {d['basis']['price']} 위 마감. 해당 근거를 재사용하지 않으며 주된 반전·전량 종료로 대체하지 않음."
        elif d['kind']=='add_rejected':
            note=d['reason']+f"; 고점 {d['basis']['price']}"
        else:continue
        lines.append(f"| {utc(d['time_ms'])} | {d['kind']} | {note} |")
    lines += ['', '중요 구간은 사전에 등록된 Z01 62,750~62,900이며 이번 도착 기준은 상단 62,900이다. 국소 고점은 별도 구조 가격이다. 잔량 평단·본절은 장부 산식으로 구분하며 목표를 손익에 맞춰 바꾸지 않았다.', '',
        '## 실패 사례를 남긴 수정','',
        '첫 시험에서는 8월 16일 16:12에 과거 고점의 첫 접촉만으로 0.001 BTC를 추가하고 16:15에 다시 한도 복구 축소했다. 고점 ID가 다르다는 사실이 새로운 구조의 독립성을 입증하지 못했다.',
        '수정 시험은 직전 실제 증가를 만든 판단 뒤에 형성·확인된 고점만 추가 근거로 인정한다. 이 수정은 개발 자료에서 도출했으므로 일반화 검증이 아니다. 수정 전 실패 경로와 비용/유동성 민감도를 함께 보존한다.', '',
        '| 경로 | 최초 BTC | 최대 BTC | 최종 BTC | 평가 순손익 | 마지막에 청산했다면 | 최대 종가 DD | 비용 | 펀딩 지급(음수=수취) |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    summaries={'freshness_trial':s,**{k:v['summary'] for k,v in result['comparisons'].items()}}
    for name,a in summaries.items():
        f=a['final']
        lines.append(f"| {name} | {a['initial_quantity']} | {a['maximum_quantity']} | {f['quantity']} | {f['total_net']:.6f} | {f['net_if_closed']:.6f} | {a['maximum_close_drawdown']:.6f} | {a['fees']:.6f} | {a['funding_paid']:.6f} |")
    lines += ['', '펀딩은 원본 정산 시각과 markPrice를 사용했다. 밀리초가 있는 시각을 정시로 반올림하지 않았다. 미래 펀딩은 진입·추가 근거에 쓰지 않았다. 수수료·슬리피지·체결 가능량을 바꾼 비교는 매번 전체 계좌를 재생했다.',
        '평가·DD는 거래가격 기반 대용치이며 거래소 mark equity·청산·실제 호가 경로를 재현하지 않는다. 봉 중 고점 기준 불리한 DD 대용치도 JSON에 별도로 남겼다. 운영 비용은 미상이다. 표의 소액 양수를 비용 전부를 반영한 수익성 확증으로 해석하지 않는다.', '',
        '## 단계 상태','',
        '2단계: 실제 시점에서 진입→추가→축소의 조건부 이유와 계좌 경로를 연결했다. 오래된 구조 재사용이라는 충돌을 찾아 실패와 수정 경로를 모두 보존했다.',
        '3단계: 이 사례에 필요한 발동·금지·정보 부족 처리를 시험 명세로 작성했다. 주된 이동 선정, 시간 창 역할, 새 반응의 독립성, 방향 불확실 때 전량 종료의 일반 기준은 여전히 미검증이다.',
        '4단계의 서로 다른 시장 검토와 5단계 운영 엔진 연결, 6단계 미관측 자료 평가는 미실행이다. 실제 체결·계좌 연결도 하지 않았다.', '']
    return '\n'.join(lines)


if __name__=='__main__':main()
