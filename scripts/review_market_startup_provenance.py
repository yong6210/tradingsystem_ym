"""Diagnose missing historical landmarks without promoting a direction rule."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from review_market_judgment_regimes import ROOT,MINUTE,DAY,CONFIG,load_rows,prepare,snapshot,stamp,utc
from app.research.recovery.protected_structure import reduce_structure
from app.research.recovery.structure_review import completed_bars,observe_structure

DOC=ROOT/'docs/research/MARKET_STARTUP_PROVENANCE_TRIAL.md'
OUT=ROOT/'reports/validation/market_startup_provenance_20260919'
FIELDS=('id','kind','price','pivot_bar_end_ms','available_ms')


def pivots(scale):return [{k:p[k] for k in FIELDS} for p in scale['observations']['pivots']]


def key(c):
    if c is None:return None
    return (c['side'],c['status'],c['formed_ms'],c.get('invalidated_ms'),tuple((c[k]['id'],c[k]['price'],c[k]['available_ms'])
            for k in ('prior_reaction','broken','protected')))


def missing_landmark(p,other_pivots,*,history_start,minutes,t):
    if p['available_ms']>t:raise ValueError('future landmark')
    same=[x for x in other_pivots if x['id']==p['id'] and x['price']==p['price'] and x['available_ms']<=t]
    if same:return None
    if p['pivot_bar_end_ms']<=history_start:return 'formed_before_or_at_history_start'
    # With two left bars, first possible center is the third complete bar.
    width=minutes*MINUTE
    first_complete_end=((history_start+width-1)//width+1)*width
    if p['pivot_bar_end_ms']<first_complete_end+2*width:return 'insufficient_left_context_at_boundary'
    return 'not_observed_in_other_history'


def compare_nodes(nodes,registries,starts,t):
    if len(nodes)!=2 or len(registries)!=2 or len(starts)!=2:raise ValueError('two histories required')
    a,b=[n['candidate'] for n in nodes]
    for c in (a,b):
        if c and (c['formed_ms']>t or any(c[k]['available_ms']>t for k in ('prior_reaction','broken','protected'))):
            raise ValueError('future candidate evidence')
    if key(a)==key(b):return dict(status='same_basis_and_state',missing=[])
    missing=[]
    for i,n in enumerate(nodes):
        c=n['candidate']
        if c is None:continue
        if c['formed_ms']>t:raise ValueError('future candidate')
        for role in ('prior_reaction','broken','protected'):
            p=c[role];reason=missing_landmark(p,registries[1-i],history_start=starts[1-i],minutes=n['minutes'],t=t)
            if reason:missing.append(dict(source_history=i,other_history=1-i,role=role,landmark=deepcopy(p),reason=reason))
    return dict(status='different_with_missing_landmarks' if missing else 'different_despite_current_landmarks_available',missing=missing)


def focal(rows,cfg):
    end=stamp('2026-08-04T00:00:00Z');starts=[end-8*DAY,end-16*DAY]
    scales=[prepare(rows,s,end,cfg)['scales'][240] for s in starts]
    short,long=scales;short_p,long_p=pivots(short),pivots(long)
    assert short['bars']==[b for b in long['bars'] if b['end_ms']>starts[0]]
    variants={
        'short_original':(short['bars'],short_p),
        'long_original':(long['bars'],long_p),
        'long_prices_short_landmarks':(long['bars'],short_p),
        'long_prices_only_post_boundary_landmarks':(long['bars'],[p for p in long_p if p['pivot_bar_end_ms']>starts[0]]),
        'long_without_boundary_high':(long['bars'],[p for p in long_p if p['id']!=f"high:{stamp('2026-07-27T08:00:00Z')}"]),
    }
    results={name:reduce_structure(bars,ps,confirmation_mode=cfg['structure_mode']) for name,(bars,ps) in variants.items()}
    assert results['short_original']==short['trial'] and results['long_original']==long['trial']
    assert results['long_prices_short_landmarks']==results['short_original']
    assert results['long_prices_only_post_boundary_landmarks']==results['short_original']
    times=[stamp(x) for x in ('2026-07-28T00:00:00Z','2026-07-30T12:00:00Z','2026-07-31T16:00:00Z','2026-08-04T00:00:00Z')]
    for t in times:
        for name,(bars,ps) in variants.items():
            truncated=reduce_structure([b for b in bars if b['end_ms']<=t],[p for p in ps if p['available_ms']<=t],confirmation_mode=cfg['structure_mode'])
            assert truncated['events']==[e for e in results[name]['events'] if e['available_ms']<=t]
        for start,original in zip(starts,scales):
            source=[r for r in rows if start<r['end_ms']<=t]
            bars=completed_bars(source,t,240);obs=observe_structure(bars)
            assert [{k:p[k] for k in FIELDS} for p in obs['pivots']]==[p for p in pivots(original) if p['available_ms']<=t]
    marker=next(p for p in long_p if p['id']==f"high:{stamp('2026-07-27T08:00:00Z')}")
    first_short=short['bars'][0]['end_ms']
    required_left=[marker['pivot_bar_end_ms']-2*240*MINUTE,marker['pivot_bar_end_ms']-240*MINUTE]
    divergence=[]
    for t in times:
        records=[]
        for start in starts:
            view=snapshot(prepare(rows,start,t,cfg),t)
            records.append(next(n for n in view['nodes'] if n['minutes']==240))
        comparison=compare_nodes(records,[short_p,long_p],starts,t)
        divergence.append(dict(time_ms=t,utc=utc(t),nodes=records,comparison=comparison,
            close=next(b['close'] for b in long['bars'] if b['end_ms']==t)))
    return dict(short_start_ms=starts[0],long_start_ms=starts[1],end_ms=end,variants=results,
        identical_common_bars=True,divergence=divergence,boundary=dict(landmark=marker,
        first_short_bar_ms=first_short,required_left_bar_ends=required_left,
        absent_left_bar_ends=[x for x in required_left if x not in {b['end_ms'] for b in short['bars']}]))


def agreement_followup(rows,cfg):
    """Retrospective visible agreement is not full observer-state convergence."""
    end=stamp('2026-08-17T00:00:00Z');series=[]
    for start in (stamp('2026-07-27T00:00:00Z'),stamp('2026-07-19T00:00:00Z')):
        bars=completed_bars([b for b in rows if start<b['end_ms']<=end],end,240)
        obs=observe_structure(bars)
        ps=[{k:p[k] for k in FIELDS} for p in obs['pivots']]
        trial=reduce_structure(bars,ps,confirmation_mode=cfg['structure_mode'])
        c=None;last_invalidated=None;last_action=None;points={};index=0
        for b in bars:
            t=b['end_ms']
            while index<len(trial['events']) and trial['events'][index]['available_ms']<=t:
                e=trial['events'][index];last_action=e['action']
                if last_action=='candidate_invalidated':
                    c=dict(c,status='invalidated',invalidated_ms=e['available_ms']);last_invalidated=e['available_ms']
                else:c={k:deepcopy(e[k]) for k in ('side','status','formed_ms','protected','broken','prior_reaction')}
                index+=1
            points[t]=dict(candidate=deepcopy(c),retained_last_invalidated_ms=last_invalidated,last_action=last_action)
        series.append(points)
    common=[t for t in series[0] if all(x[t]['candidate'] is not None for x in series)
            and key(series[0][t]['candidate'])==key(series[1][t]['candidate'])]
    first=common[0] if common else None
    result=dict(end_ms=end,first_visible_agreement_ms=first,
        retrospective_description_not_entry_gate=True,full_state_equivalence_verified=False)
    if first is not None:
        result.update(at_first_agreement=[x[first] for x in series],
            later_visible_differences=sum(key(series[0][t]['candidate'])!=key(series[1][t]['candidate']) for t in series[0] if t>=first))
        # Independently rebuild at the first visible agreement without later prices.
        for start,expected in zip((stamp('2026-07-27T00:00:00Z'),stamp('2026-07-19T00:00:00Z')),result['at_first_agreement']):
            bars=completed_bars([b for b in rows if start<b['end_ms']<=first],first,240)
            obs=observe_structure(bars);ps=[{k:p[k] for k in FIELDS} for p in obs['pivots']]
            trial=reduce_structure(bars,ps,confirmation_mode=cfg['structure_mode'])
            assert key(trial['candidate'])==key(expected['candidate'])
            invalid=[e['available_ms'] for e in trial['events'] if e['action']=='candidate_invalidated']
            assert (invalid[-1] if invalid else None)==expected['retained_last_invalidated_ms']
    return result


def audit_existing(rows,cfg,old):
    output=[];cache={}
    cases=[(c['label'],c['points']) for c in old['cases']]
    cases.append(('original_nine',[dict(time_ms=stamp(p['utc']),utc=p['utc'],views=p['views']) for p in old['original_case_reassessment']]))
    for label,points in cases:
        records=[]
        for p in points:
            t=p['time_ms'];views=p['views']
            # Snapshot stores node data, not start dates; these are the original replay contracts.
            if label=='original_nine':starts=[t-days*DAY for days in cfg['history_days']]
            else:
                c=next(c for c in old['cases'] if c['label']==label)
                starts=[c['case']['start_ms']-days*DAY for days in cfg['history_days']]
            end=max(x['time_ms'] for x in points) if label!='original_nine' else t
            prepared=[]
            for s in starts:
                k=(s,end)
                if k not in cache:cache[k]=prepare(rows,s,end,cfg)
                prepared.append(cache[k])
            for m in cfg['structure_minutes']:
                nodes=[next(n for n in v['nodes'] if n['minutes']==m) for v in views]
                # Ensure saved views really correspond to this exact original source contract.
                for n,prep in zip(nodes,prepared):
                    rebuilt=next(x for x in snapshot(prep,t)['nodes'] if x['minutes']==m)
                    assert n==rebuilt
                result=compare_nodes(nodes,[pivots(x['scales'][m]) for x in prepared],starts,t)
                records.append(dict(time_ms=t,utc=p['utc'],minutes=m,history_starts=starts,nodes=nodes,comparison=result))
        counts={status:sum(r['comparison']['status']==status for r in records) for status in
                ('same_basis_and_state','different_with_missing_landmarks','different_despite_current_landmarks_available')}
        output.append(dict(label=label,comparisons=len(records),counts=counts,records=records))
        print(json.dumps(dict(label=label,**counts)),flush=True)
    return output


def render(r):
    f=r['focal'];lines=['# 최초 기준 출처와 자료 경계 대조','',
        '긴 자료를 정답으로 선택하지 않는다. 가격과 판단 규칙을 바꾸지 않고 참조 가능한 과거 근거 차이를 분해했다. 주문·새 방향 승인은 없다.','',
        '| 대조군 | 형성·갱신·무효화 사건 | 최종 상태 |','| --- | --- | --- |']
    for name,v in f['variants'].items():
        events='; '.join(utc(e['available_ms'])+' '+e['action']+' '+str(e.get('protected',{}).get('price',e.get('close'))) for e in v['events'])
        c=v['candidate'];lines.append(f"| {name} | {events} | {c['side'] if c else None} / {c['status'] if c else None} |")
    lines+=['','## 같은 시각의 다른 근거','','| UTC | 완료 종가 | 짧은 이력 | 긴 이력 | 차이 분류 |','| --- | ---: | --- | --- | --- |']
    for p in f['divergence']:
        cells=[]
        for n in p['nodes']:
            c=n['candidate'];cells.append('없음' if c is None else f"{c['side']} / {c['status']} / {c['protected']['price']}")
        lines.append(f"| {p['utc']} | {p['close']} | {' | '.join(cells)} | {p['comparison']['status']} |")
    lines+=['','## 기존 모든 시점의 출처 점검','','한 시점×관찰 창의 두 이력 비교다. 방향 정확도나 진입 수가 아니다. 세 근거가 같아도 과거 상태 경로가 다를 수 있다.','',
        '| 사례 | 비교 수 | 같은 근거·상태 | 누락 근거 동반 | 현재 근거는 있지만 상태 차이 |','| --- | ---: | ---: | ---: | ---: |']
    for c in r['existing_case_audit']:
        n=c['counts'];lines.append(f"| {c['label']} | {c['comparisons']} | {n['same_basis_and_state']} | {n['different_with_missing_landmarks']} | {n['different_despite_current_landmarks_available']} |")
    follow=r['agreement_followup'];first=follow['first_visible_agreement_ms']
    lines+=['','## 보이는 기준 일치와 내부 이력 차이','',
        '첫 표시 기준 일치: '+(utc(first) if first else '없음')+'. 이후 자료를 이용한 설명용 집계이며 진입 조건이 아니다.',
        '그 시점의 마지막 무효화 이력: '+str([x['retained_last_invalidated_ms'] for x in follow.get('at_first_agreement',[])])+'. 전체 상태 동등성은 검증하지 않았다.']
    lines+=['','자료 시작 이전 근거와 경계의 왼쪽 봉 부족을 구분했다. 경계 고점 하나를 보완해도 오래된 근거의 부재를 해결하지 못했다. 피벗 제거 실험은 원인 분해이며 사용할 전략이 아니다.',
            '최초 기준의 정당성·충분한 준비 기간·실제 주된 방향은 여전히 미검증이다. 4단계 미통과, 5·6단계 보류.','']
    return '\n'.join(lines)


def main():
    rows,sources=load_rows();cfg=json.loads(CONFIG.read_text())
    oldpath=ROOT/'reports/validation/market_judgment_regimes_20260919/review.json'
    old=json.loads(oldpath.read_text());result=dict(status='startup_provenance_audit_not_strategy_selection',
        focal=focal(rows,cfg),existing_case_audit=audit_existing(rows,cfg,old),agreement_followup=agreement_followup(rows,cfg),
        orders_generated=0,new_exposure_allowed=False,checks=dict(common_bars='PASS',future_truncation='PASS',saved_view_rebuild='PASS'))
    sources += [CONFIG,DOC,Path(__file__),oldpath,ROOT/'scripts/review_market_judgment_regimes.py',
                ROOT/'app/research/recovery/protected_structure.py',ROOT/'app/research/recovery/structure_review.py']
    result['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');(OUT/'review.md').write_text(render(result))


if __name__=='__main__':main()
