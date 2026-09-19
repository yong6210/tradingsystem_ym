"""Frozen descriptive case selection and causal judgment review, no order engine."""
import csv
import hashlib
import io
import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from replay_cycling_trial_v1 import ROOT, stamp
from review_market_judgment_sequence import CHECKPOINTS
from review_first_candidate_account import contacts
from app.research.recovery.structure_review import completed_bars, observe_structure
from app.research.recovery.protected_structure import protected_structure
from app.research.recovery.models import dec, jsonable
from app.research.recovery.position_alternatives import PositionExample, ExampleCosts, alternative
from app.research.recovery.cycling_admission import Capacity
from app.research.recovery.recovery_capacity_review import review_capacity
from app.research.recovery.campaign_recovery_review import net_if_closed
from app.research.recovery.round_trip_review import round_trip

CONFIG=ROOT/'configs/research/market_judgment_regime_review.json'
DOC=ROOT/'docs/research/MARKET_JUDGMENT_GENERAL_TRIAL.md'
DATA=ROOT/'data/historical/btcusdc_public_20260917'
MINUTE=60000;HOUR=60*MINUTE;DAY=24*HOUR


def utc(t):return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()


def load_rows():
    rows=[];sources=[]
    for month in ('07','08'):
        path=DATA/f'klines/BTCUSDC-1m-2026-{month}.zip';raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=path.with_name(path.name+'.CHECKSUM').read_text().split()[0]:
            raise ValueError('archive checksum mismatch')
        sources.append(path)
        with ZipFile(io.BytesIO(raw)) as z,z.open(z.namelist()[0]) as fp:
            for r in csv.DictReader(io.TextIOWrapper(fp)):
                rows.append(dict(end_ms=int(r['open_time'])+MINUTE,**{k:float(r[k]) for k in ('open','high','low','close')}))
    return rows,sources


def select_cases(rows,cfg):
    hours=completed_bars(rows,stamp(cfg['selection_end']),60)
    thresholds=cfg['label_thresholds'];daily=[]
    for start in range(stamp(cfg['selection_start']),stamp(cfg['selection_end']),DAY):
        before=[b for b in hours if start-49*HOUR<=b['end_ms']<=start]
        block=[b for b in hours if start<b['end_ms']<=start+DAY]
        if len(before)<49 or len(block)!=24:continue
        unit=sum(b['high']-b['low'] for b in before[-24:])/24
        if unit<=0:continue
        origin=before[-1]['close'];prior_move=origin-before[-49]['close'];net=block[-1]['close']-origin
        trend=1 if prior_move>=thresholds['prior_trend_atr']*unit else -1 if prior_move<=-thresholds['prior_trend_atr']*unit else 0
        prior_high=max(b['high'] for b in before[-24:]);prior_low=min(b['low'] for b in before[-24:])
        high=max(b['high'] for b in block);low=min(b['low'] for b in block);span=high-low
        peak=trough=origin;pullback=rebound=travel=0;previous=origin;anchor=origin;phase=0;reversals=0
        for b in block:
            pullback=max(pullback,peak-b['low']);rebound=max(rebound,b['high']-trough)
            peak=max(peak,b['high']);trough=min(trough,b['low'])
            travel+=abs(b['close']-previous);previous=b['close']
            if abs(b['close']-anchor)>=unit:
                direction=1 if b['close']>anchor else -1
                reversals+=bool(phase and direction!=phase);phase=direction;anchor=b['close']
        # A later bar must return; within-bar price order is never inferred.
        failed=(trend==-1 and net<0 and any(b['high']>prior_high and any(x['close']<prior_high for x in block[i+1:]) for i,b in enumerate(block))) or (trend==1 and net>0 and any(b['low']<prior_low and any(x['close']>prior_low for x in block[i+1:]) for i,b in enumerate(block)))
        reversal=(trend==1 and net<=-thresholds['reversal_net_atr']*unit and all(b['close']<prior_low for b in block[-6:])) or (trend==-1 and net>=thresholds['reversal_net_atr']*unit and all(b['close']>prior_high for b in block[-6:]))
        labels=dict(rising_pullback=trend==1 and net>0 and pullback>=thresholds['pullback_atr']*unit,
            falling_rebound=trend==-1 and net<0 and rebound>=thresholds['pullback_atr']*unit,
            range_cycles=span>0 and span<=thresholds['box_max_range_atr']*unit and abs(net)<=thresholds['box_max_net_fraction']*span and reversals>=thresholds['box_min_reversals'],
            failed_break_return=bool(failed),main_reversal_candidate=bool(reversal),
            oneway_adverse=abs(net)>=thresholds['oneway_net_atr']*unit and travel>0 and abs(net)/travel>=thresholds['oneway_efficiency'])
        daily.append(dict(start_ms=start,end_ms=start+DAY,utc=utc(start),labels=labels,
            metrics=dict(prior_trend=trend,prior_move=prior_move,net=net,mean_prior_hour_range=unit,
                         prior_high=prior_high,prior_low=prior_low,range=span,pullback=pullback,rebound=rebound,
                         reversals=reversals,efficiency=abs(net)/travel if travel else 0)))
    selected=[];used=set()
    for label in cfg['labels']:
        eligible=[d for d in daily if d['labels'][label] and d['start_ms'] not in used]
        case=eligible[0] if eligible else None
        if case:used.add(case['start_ms'])
        selected.append(dict(label=label,case=case))
    return selected,daily


def signature(c):
    if c is None:return None
    return (c['side'],c['prior_reaction']['price'],c['broken']['price'],c['protected']['price'])


def role_context(nodes):
    """Price/time containment, never timeframe votes. Inputs must already be causal."""
    grouped={}
    for n in nodes:
        c=n['candidate']
        if c is None or c['status']!='active':continue
        grouped.setdefault(signature(c),[]).append(n)
    unique=[]
    for key,group in grouped.items():
        chosen=deepcopy(max(group,key=lambda x:x['candidate']['formed_ms']))
        chosen['duplicate_timeframes']=[x['minutes'] for x in group];unique.append(chosen)
    def contains(a,b):
        ca,cb=a['candidate'],b['candidate']
        return (ca['prior_reaction']['pivot_bar_end_ms']<cb['prior_reaction']['pivot_bar_end_ms'] and
                all(a['low']<=cb[k]['price']<=a['high'] for k in ('prior_reaction','broken','protected')))
    roots=[];containing=[]
    for n in unique:
        others=[x for x in unique if x is not n]
        supporters=[x for x in others if x['candidate']['side']==n['candidate']['side'] and contains(n,x) and
                    x['candidate']['protected']['pivot_bar_end_ms']>n['candidate']['protected']['pivot_bar_end_ms']]
        if others and all(contains(n,x) for x in others):containing.append(n)
        if supporters and all(contains(n,x) for x in others):roots.append(n)
    if len(roots)!=1:
        blocker=('no_active_structure' if not unique else 'only_one_distinct_active_structure' if len(unique)==1 else
                 'no_price_time_containment' if not containing else 'no_later_same_side_structure' if not roots else 'multiple_eligible_roots')
        return dict(status='uncertain',side=None,root=None,reason='no_unique_containing_impulse_with_later_same_side_structure',blocker=blocker,active_groups=len(unique))
    return dict(status='supported_trial',side=roots[0]['candidate']['side'],root=roots[0],
                reason='unique_price_time_containment_not_timeframe_majority',active_groups=len(unique))


def prepare(rows,history_start,end,cfg):
    known=[r for r in rows if history_start<r['end_ms']<=end]
    scales={}
    for m in cfg['structure_minutes']:
        bars=completed_bars(known,end,m)
        scales[m]=dict(bars=bars,trial=protected_structure(bars,confirmation_mode=cfg['structure_mode']),
                       observations=observe_structure(bars))
    return dict(rows=known,scales=scales,history_start=history_start)


def snapshot(prepared,t):
    nodes=[]
    for m,s in prepared['scales'].items():
        c=None
        for e in s['trial']['events']:
            if e['available_ms']>t:break
            if e['action']=='candidate_invalidated':
                if c:c=dict(c,status='invalidated',invalidated_ms=e['available_ms'])
            else:
                keys=('side','status','formed_ms','protected','broken','prior_reaction','break_ms','evidence_available_ms','opposition_review')
                c={k:deepcopy(e[k]) for k in keys if k in e}
        if c:
            # Include the entire formation bar, not just its final minute.
            block=[b for b in prepared['rows'] if c['prior_reaction']['pivot_bar_end_ms']-m*MINUTE<b['end_ms']<=t]
            nodes.append(dict(minutes=m,candidate=c,low=min(b['low'] for b in block),high=max(b['high'] for b in block)))
        else:nodes.append(dict(minutes=m,candidate=None,low=None,high=None))
    return dict(time_ms=t,nodes=nodes,context=role_context(nodes))


def stable_context(views):
    contexts=[v['context'] for v in views]
    def key(c):
        return (c['status'],c['side'],None if c['root'] is None else (signature(c['root']['candidate']),c['root']['candidate']['formed_ms']))
    if len({key(c) for c in contexts})>1:
        return dict(status='uncertain',side=None,root=None,reason='history_start_sensitive',blocker='history_start_sensitive',
                    history_alternatives=[dict(status=c['status'],side=c['side'],root_signature=None if c['root'] is None else signature(c['root']['candidate'])) for c in contexts])
    return contexts[0]


def target_at(prepared,t,side,mark):
    candidates=[]
    for m,s in prepared['scales'].items():
        broken={e['pivot_id'] for e in s['observations']['events'] if e['kind']=='close_break' and e['available_ms']<=t}
        for p in s['observations']['pivots']:
            if p['available_ms']<=t and p['id'] not in broken and p['kind']==('high' if side==1 else 'low') and side*(p['price']-mark)>0:
                candidates.append(dict(price=p['price'],available_ms=p['available_ms'],id=p['id'],minutes=m,type='structural_price_not_volume_zone'))
    return min(candidates,key=lambda p:abs(p['price']-mark)) if candidates else None


def action_review(*,context,position,costs,mark,t,account,reaction,target,last_growth,
                  original_root=None,prior_invalidated_ms=None,target_hit=False,reduction_used=False):
    """Returns a review intention, not an executable order or revised position."""
    result=dict(action='wait',reason=None,quantity=dec(0),position=position,target=target)
    equity=position.starting_equity+position.pnl(mark)
    free=equity-position.quantity*dec(mark)/costs.leverage
    stress=[net_if_closed(position,costs,dec(mark)-position.side*dec(move)) for move in account['stress_moves']]
    result.update(free_margin_proxy=free,stress_net=stress)
    if position.quantity and min(position.pnl(mark),net_if_closed(position,costs,mark))<=-dec(account['internal_drawdown_halt']):
        result.update(action='account_halt_review',reason='loss_from_initial_equity_already_exceeds_halt',quantity=position.quantity);return result
    if position.quantity and (free<dec(account['reserve_margin']) or min(stress)<-dec(account['total_stress_budget']) or position.quantity>dec(account['maximum_total_quantity'])):
        for units in range(1,int(position.quantity/costs.step)+1):
            q=units*costs.step
            if q<dec(account['minimum_quantity']) or q*costs.execution(mark,-position.side)<dec(account['minimum_notional']):continue
            after=alternative(position,costs,mark=mark,action='partial_loss_example',quantity=q,stress_moves=account['stress_moves'])['after']
            room=after.starting_equity+after.pnl(mark)-after.quantity*dec(mark)/costs.leverage
            scenarios=[net_if_closed(after,costs,dec(mark)-after.side*dec(move)) for move in account['stress_moves']]
            if room>=dec(account['reserve_margin']) and min(scenarios)>=-dec(account['total_stress_budget']) and after.quantity<=dec(account['maximum_total_quantity']):
                result.update(action='capacity_reduction_review',reason='minimum_executable_reduction_restores_limits',quantity=q);return result
        result.update(action='account_limit_unresolved',reason='no_executable_reduction_restores_limits');return result
    side=context['side']
    if position.quantity and side is not None and side!=position.side:
        root=context['root']['candidate']
        if original_root is not None and original_root['candidate']['side']==position.side and prior_invalidated_ms is not None and root['formed_ms']>prior_invalidated_ms:
            result.update(action='exit_before_any_opposite_entry',reason='original_main_basis_failed_then_opposite_structure',quantity=position.quantity);return result
    if position.quantity and target_hit and not reduction_used:
        from decimal import ROUND_CEILING
        quantity=(position.quantity/2/costs.step).to_integral_value(rounding=ROUND_CEILING)*costs.step
        if quantity>=dec(account['minimum_quantity']) and quantity*costs.execution(mark,-position.side)>=dec(account['minimum_notional']):
            result.update(action='reduce_half',reason='predeclared_target_reached',quantity=quantity);return result
    if side is None:
        result['reason']='direction_unassessed';return result
    if position.quantity and side!=position.side:
        result['reason']='opposite_candidate_without_original_thesis_reversal_proof';return result
    if reaction is None:
        result['reason']='no_fresh_reaction_at_this_checkpoint';return result
    if reaction['available_ms']>t or reaction['pivot_bar_end_ms']>reaction['available_ms']:
        result['reason']='reaction_not_available';return result
    if position.quantity and min(reaction['pivot_bar_end_ms'],reaction['available_ms'])<=last_growth:
        result['reason']='historical_marker_not_new_after_growth';return result
    if position.quantity and side*(dec(mark)-position.average)>=0:
        result['reason']='no_adverse_price_for_addition_trial';return result
    if target is None or target['available_ms']>t:
        result['reason']='no_available_target';return result
    # The flat scenario's bookkeeping side follows the assessed candidate only here.
    p=replace(position,side=side) if not position.quantity else position
    room=round_trip(costs,side=side,quantity='.006',entry_mark=mark,exit_mark=target['price'])
    result['marginal_round_trip']=room
    if room['net']<=0:
        result['reason']='nearest_target_does_not_cover_costs';return result
    cap=Capacity(t,max(dec(0),free),account['reserve_margin'],dec(mark)/costs.leverage,account['maximum_total_quantity'],
                 account['total_stress_budget'] if position.quantity else account['initial_stress_budget'],account['stress_moves'])
    review=review_capacity(p,costs,mark=mark,quote_ms=t,capacity=cap,requested='.006' if position.quantity else account['maximum_total_quantity'],
        liquidity_qty=account['assumed_liquidity_quantity'],minimum_quantity=account['minimum_quantity'],minimum_notional=account['minimum_notional'],now_ms=t,max_age_ms=0)
    result['capacity']=review
    if not review['capacity_quantity']:
        result['reason']='no_executable_capacity';return result
    result.update(action='add_candidate' if position.quantity else 'entry_candidate',reason='trial_context_reaction_room_capacity',quantity=review['capacity_quantity'])
    return result


def main():
    cfg=json.loads(CONFIG.read_text());rows,sources=load_rows()
    account_path=ROOT/cfg['account_config'];account=json.loads(account_path.read_text())
    selected,daily=select_cases(rows,cfg)
    out=ROOT/'reports/validation/market_judgment_regimes_20260919';out.mkdir(parents=True,exist_ok=True)
    # This inventory is written before action evaluation, with no outcome filter.
    selection=dict(config=cfg,cases=selected,daily_features=daily,selection_uses_future_shape=True,used_for_trade_decisions=False)
    (out/'selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2)+'\n')
    costs=ExampleCosts(*(account[k] for k in ('fee','half_spread','slippage','tick','step','leverage')))
    reviews=[];failures=[]
    funding=json.loads((DATA/'funding_history.json').read_text())
    for item in selected:
        case=item['case']
        if case is None:
            failures.append(dict(label=item['label'],reason='no_matching_distinct_day_under_frozen_thresholds'));continue
        start,end=case['start_ms'],case['end_ms']
        prepared=[prepare(rows,start-days*DAY,end,cfg) for days in cfg['history_days']]
        actual=[b for b in rows if start<=b['end_ms']<=end];bytime={b['end_ms']:b for b in actual}
        short_contacts=contacts(prepared[-1]['rows'],end)
        # Price reflection reuses the proven first-contact observer for long support.
        mirror=[dict(b,open=200000-b['open'],high=200000-b['low'],low=200000-b['high'],close=200000-b['close']) for b in prepared[-1]['rows']]
        long_contacts=contacts(mirror,end)
        for points in long_contacts.values():
            for p in points:p['price']=200000-p['price']
        reactions={-1:short_contacts,1:long_contacts}
        first=stable_context([snapshot(p,start) for p in prepared]);initial_mark=bytime[start]['close']
        fixed_targets={side:target_at(prepared[-1],start,side,initial_mark) for side in (-1,1)}
        hit={side:next((b['end_ms'] for b in actual if b['end_ms']>start and fixed_targets[side] and
                       (b['high']>=fixed_targets[side]['price'] if side==1 else b['low']<=fixed_targets[side]['price'])),None) for side in (-1,1)}
        times=set(range(start,end+1,6*HOUR))
        times.update(t for contacts_by_time in reactions.values() for t in contacts_by_time if start<=t<=end)
        times.update(t for t in hit.values() if t is not None)
        points=[]
        original_root=first.get('root');invalidated=None
        if original_root:
            c=original_root['candidate'];m=original_root['minutes']
            bars=prepared[-1]['scales'][m]['bars']
            invalidated=next((b['end_ms'] for b in bars if b['end_ms']>start and c['side']*(b['close']-c['protected']['price'])<0),None)
        for t in sorted(times):
            views=[snapshot(p,t) for p in prepared];context=stable_context(views);mark=bytime[t]['close']
            # Verify full-run event slicing against an independently truncated rebuild.
            if t in range(start,end+1,6*HOUR):
                for days,view in zip(cfg['history_days'],views):
                    assert view==snapshot(prepare([r for r in rows if r['end_ms']<=t],start-days*DAY,t,cfg),t)
            scenarios=[]
            for side,qty,name in ((1,'0','flat'),(1,'.006','hypothetical_long_006'),(-1,'.006','hypothetical_short_006')):
                q=dec(qty);entry=costs.execution(initial_mark,side)
                funding_paid=sum((side*q*dec(f['markPrice'])*dec(f['fundingRate']) for f in funding if start<f['fundingTime']<=t),dec(0))
                p=PositionExample(side,q,entry if q else None,0,q*entry*costs.fee+funding_paid,q*entry*costs.fee+funding_paid,1000)
                direction=context['side'] or side
                candidates=reactions[direction].get(t,[])
                fresh=[x for x in candidates if min(x['pivot_bar_end_ms'],x['available_ms'])>start]
                reaction=(fresh or candidates or [None])[0]
                target=fixed_targets[side] if q else target_at(prepared[-1],t,direction,mark)
                result=action_review(context=context,position=p,costs=costs,mark=mark,t=t,account=account,reaction=reaction,target=target,last_growth=start,
                    original_root=original_root,prior_invalidated_ms=invalidated if invalidated is not None and invalidated<=t else None,
                    target_hit=bool(q and hit[side] is not None and hit[side]<=t),reduction_used=bool(q and hit[side] is not None and hit[side]<t))
                scenarios.append(dict(name=name,result=result,reaction=reaction))
            points.append(dict(utc=utc(t),time_ms=t,mark=mark,context=context,views=views,scenarios=scenarios))
        counts=Counter(s['result']['action'] for p in points for s in p['scenarios'])
        uncertain=sum(p['context']['side'] is None for p in points)
        reviews.append(dict(label=item['label'],case=case,points=points,initial_context=first,counts=dict(counts),uncertain_checkpoints=uncertain,
                            blockers=dict(Counter(p['context'].get('blocker') for p in points if p['context']['side'] is None)),
                            fixed_targets=fixed_targets,original_basis_invalidated_ms=invalidated))
        print(json.dumps(dict(label=item['label'],date=case['utc'],checkpoints=len(points),uncertain=uncertain,actions=dict(counts))),flush=True)
    original=[]
    for date,_,_,_ in CHECKPOINTS:
        t=stamp(date)
        views=[snapshot(prepare(rows,t-days*DAY,t,cfg),t) for days in cfg['history_days']]
        original.append(dict(utc=date,context=stable_context(views),views=views))
    original_path=ROOT/'reports/validation/main_direction_opposition_20260919/review.json'
    prior_readings=json.loads(original_path.read_text())['case_readings']
    for item,prior in zip(original,prior_readings):
        assert item['utc']==prior['utc']
        prior_side=-1 if prior['trial_thesis']=='주된 숏 가설 유지' else None
        item['prior_case_side']=prior_side;item['same_direction_as_prior_case']=item['context']['side']==prior_side
    sources += [CONFIG,DOC,account_path,Path(__file__),DATA/'funding_history.json',ROOT/'scripts/review_first_candidate_account.py',ROOT/'scripts/review_market_judgment_sequence.py',original_path]
    sources += [ROOT/'app/research/recovery'/name for name in ('protected_structure.py','structure_review.py','position_alternatives.py','round_trip_review.py','recovery_capacity_review.py','campaign_recovery_review.py','cycling_admission.py','models.py')]
    result=dict(status='development_judgment_review_not_strategy_backtest',cases=reviews,selection_failures=failures,original_case_reassessment=original,
        promotion='blocked_pending_role_and_transition_validation',orders_generated=0,
        checks=dict(causal_prefix_rebuild='PASS',future_case_label_not_passed_to_judgment=True),
        limitations=['three fixed inventory snapshots, no continuous fills or account returns','case labels are retrospective descriptions, not ground truth',
                     'hypothetical account peak and actual execution state not reconstructed; account-halt/execution gates not certified',
                     'structural price targets are not volume zones; significance unverified'],
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (out/'review.json').write_text(json.dumps(jsonable(result),ensure_ascii=False,indent=2)+'\n')
    (out/'review.md').write_text(render(result))


def render(result):
    names=dict(rising_pullback='상승 중 큰 눌림',falling_rebound='하락 중 큰 반등',range_cycles='박스 반복',failed_break_return='돌파 실패·복귀',main_reversal_candidate='주된 전환 후보',oneway_adverse='일방향 역행')
    lines=['# 일반 판단 명세의 여섯 시장 점검','',
        '기존 2026년 8월 자료의 개발 검토다. 하루 전체 가격 형태로 사례를 선정했지만 판단에는 그 시점까지의 정보만 사용했다. 유형 이름은 실제 주된 방향의 정답이 아니다. 이력 8일·16일 차이와 원래 사례의 재판단을 함께 기록했다.',
        '무포지션·롱 0.006·숏 0.006은 각 시점의 독립 보유 상태 비교다. 연속 체결/계좌 수익률을 계산하거나 운영 엔진에 연결하지 않았다.','',
        '| 유형 | UTC 날짜 | 방향 미판정 시점/전체 | 행동 의도 |','| --- | --- | --- | --- |']
    for c in result['cases']:
        lines.append(f"| {names[c['label']]} | {c['case']['utc']} | {c['uncertain_checkpoints']}/{len(c['points'])} | {c['counts']} |")
    for f in result['selection_failures']:
        lines.append(f"| {names[f['label']]} | 미선정 | 고정 기준에 해당 날짜 없음 | 임계값을 완화하지 않음 |")
    total=sum(len(c['points']) for c in result['cases']);unknown=sum(c['uncertain_checkpoints'] for c in result['cases'])
    lines += ['',f'방향 미판정은 {unknown}/{total}개 시점이다. 선택된 장면은 서로 종속되어 있으므로 정확도·승률로 해석하지 않는다. 다음 표는 규칙이 무엇 때문에 멈췄는지 보여준다.','',
              '| 유형 | 막힌 조건 |','| --- | --- |']
    for c in result['cases']:lines.append(f"| {names[c['label']]} | {c['blockers']} |")
    lines += ['','## 시점별 방향·반대 근거·행동','']
    for c in result['cases']:
        lines += ['### '+names[c['label']]+' — '+c['case']['utc'],'',
                  '| UTC | 종가 | 주된 방향 시험 판단 | 무포지션 | 롱 보유 | 숏 보유 |','| --- | ---: | --- | --- | --- | --- |']
        for p in c['points']:
            context=p['context'];state=('롱' if context['side']==1 else '숏' if context['side']==-1 else '불확실')+' / '+context['reason']
            choices=[s['result']['action']+(' '+str(s['result']['quantity'])+' BTC' if s['result']['quantity'] else '')+' / '+str(s['result']['reason']) for s in p['scenarios']]
            lines.append(f"| {p['utc']} | {p['mark']} | {state} | {' | '.join(choices)} |")
        lines+=['','구조 가격·형성/확인 시각·원래 근거 무효화·이력별 후보·여력·왕복 비용은 JSON에 보존했다. 구조 가격을 매물대 구간으로 취급하지 않는다.','']
    lines += ['## 원래 사례 재검토','', '| UTC | 새 역할 규칙 | 이유 |','| --- | --- | --- |']
    for c in result['original_case_reassessment']:
        lines.append(f"| {c['utc']} | {c['context']['side']} | {c['context']['reason']} |")
    lines += ['','## 완료와 미완료','',
        '이번 작업은 일반 시험 명세를 고정하고 선택된 시장에서 판단 가능한 조건·대기 조건·역할 충돌을 드러낸 개발 검토다. 미선정 유형이나 방향 미판정은 검증 통과로 세지 않는다.',
        '주된 이동 역할·전환의 충분성, 구조 목표의 중요도, 불확실 때 기존 물량의 시장 종료를 아직 승인할 수 없다. 실제 계좌 고점 대비 중단·대사·체결 처리도 이 다시장 스냅샷 비교의 검증 대상 밖이다. 이전 단일 사례의 조건부 체결 검증과 구분한다.',
        '**5단계 운영 엔진 연결과 6단계 별도 자료 평가는 보류한다.** 여섯 이름을 붙였거나 행동이 결정됐다는 이유로 통과시키지 않는다.','']
    return '\n'.join(lines)


if __name__=='__main__':main()
