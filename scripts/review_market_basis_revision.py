"""Separate historical basis survival, causal reanchor and current support."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json

from review_market_direction_continuity import advance, anchor_bars, basis_key
from review_market_judgment_regimes import (
    ROOT, MINUTE, DAY, CONFIG, load_rows, prepare, snapshot, stable_context, signature, utc, stamp,
)

DOC=ROOT/'docs/research/MARKET_BASIS_REVISION_TRIAL.md'
OUT=ROOT/'reports/validation/market_basis_revision_20260919'


def identity(node):
    if node is None or node['candidate'] is None:
        return None
    c=node['candidate']
    return (node['minutes'],c['side'],c['status'],c['formed_ms'],
            tuple((c[k]['price'],c[k]['pivot_bar_end_ms'],c[k]['available_ms'])
                  for k in ('prior_reaction','broken','protected')))


def revise_basis(state, views, t):
    """Update only within the same originating observation window after its bar check."""
    s=deepcopy(state)
    if len(views)!=2 or s['root'] is None or s['reason']=='missing_anchor_closes':return s,None
    old=s['root'];c=old['candidate']
    observed=[next((n for n in v['nodes'] if n['minutes']==old['minutes']),None) for v in views]
    if not observed or any(identity(n) is None for n in observed):return s,None
    if len({identity(n) for n in observed})!=1:return s,None
    n=observed[0];new=n['candidate']
    if new['formed_ms']>t or any(new[k]['available_ms']>t for k in ('prior_reaction','broken','protected')):
        raise ValueError('future reanchor evidence')
    eligible=(new['status']=='active' and new['side']==c['side'] and new['formed_ms']>c['formed_ms'] and
              min(new['broken']['pivot_bar_end_ms'],new['protected']['pivot_bar_end_ms'])>c['formed_ms'] and
              c['side']*(new['broken']['price']-c['broken']['price'])>0 and
              c['side']*(new['protected']['price']-c['protected']['price'])>0)
    if not eligible:return s,None
    s['root']=deepcopy(n);s['last_revision_ms']=t
    return s,dict(kind='basis_revised',time_ms=t,old_root=old,new_root=deepcopy(n))


def current_support(state,views,t):
    """Returns diagnostic direction, never permission to hold, add or enter."""
    result=dict(side=None,reason='no_adopted_basis',support=[],new_exposure_allowed=False)
    if len(views)!=2:
        result['reason']='missing_history_view';return result
    if state['root'] is None:return result
    if state['side'] is None:
        result['reason']=state['reason'];return result
    root=state['root'];c=root['candidate'];groups=[]
    for view in views:
        known={}
        # A remembered root's range is recomputed from known raw minutes by the caller.
        low,high=view['basis_bounds']
        for n in view['nodes']:
            d=n['candidate']
            if d is None or d['status']!='active' or d['side']!=c['side'] or n['minutes']==root['minutes']:continue
            if d['formed_ms']>t or any(d[k]['available_ms']>t for k in ('prior_reaction','broken','protected')):
                raise ValueError('future support evidence')
            if (signature(d)!=signature(c) and
                d['prior_reaction']['pivot_bar_end_ms']>c['prior_reaction']['pivot_bar_end_ms'] and
                d['protected']['pivot_bar_end_ms']>c['protected']['pivot_bar_end_ms'] and
                all(low<=d[k]['price']<=high for k in ('prior_reaction','broken','protected'))):
                known[identity(n)]=n
        groups.append(known)
    common=set(groups[0]) if groups else set()
    for group in groups[1:]:common.intersection_update(group)
    unique={}
    for key in sorted(common):
        n=groups[0][key];unique.setdefault(signature(n['candidate']),n)
    result['support']=list(unique.values())
    if unique:result.update(side=c['side'],reason='basis_alive_with_common_later_support')
    else:result['reason']='no_common_active_later_support'
    return result


def with_bounds(views,prepared,state,t):
    result=deepcopy(views)
    if len(views)!=2:
        result['reason']='missing_history_view';return result
    if state['root'] is None:return result
    root=state['root'];begin=root['candidate']['prior_reaction']['pivot_bar_end_ms']-root['minutes']*MINUTE
    for v,p in zip(result,prepared):
        known=[b for b in p['rows'] if begin<b['end_ms']<=t]
        v['basis_bounds']=(min(b['low'] for b in known),max(b['high'] for b in known))
    return result


def replay(prepared,times,start):
    state=None;points={};events=[]
    for t in times:
        if t<start:continue
        views=[snapshot(p,t) for p in prepared];context=stable_context(views)
        state,e=advance(state,t=t,context=context,bars=anchor_bars(prepared[-1],state,t))
        if e:events.append(e)
        # Never revise after an invalidation; advance already removed the failed root.
        state,e=revise_basis(state,views,t)
        if e:events.append(e)
        guarded=current_support(state,with_bounds(views,prepared,state,t),t)
        points[t]=dict(context=context,updated_only=deepcopy(state),guarded=guarded)
    return points,events


def run_case(rows,cfg,old):
    start,end=old['start_ms'],old['end_ms'];earliest=start-min(cfg['history_days'])*DAY
    prepared=[prepare(rows,start-days*DAY,end,cfg) for days in cfg['history_days']]
    reference={p['time_ms']:p for p in old['points']}
    times=sorted(set(range(earliest,end+1,15*MINUTE))|set(reference))
    full,events=replay(prepared,times,earliest);cold,cold_events=replay(prepared,times,start)
    points=[]
    for t,p in reference.items():
        x=full[t];q=cold[t]
        points.append(dict(time_ms=t,utc=utc(t),snapshot_context=p['context'],
            fixed_memory=p['remembered'],updated_only=x['updated_only'],guarded=x['guarded'],
            reset_updated_only=q['updated_only'],reset_guarded=q['guarded']))
    for t in (min(reference),max(reference)):
        trunc=[prepare([b for b in rows if b['end_ms']<=t],start-days*DAY,t,cfg) for days in cfg['history_days']]
        prefix,pe=replay(trunc,[x for x in times if x<=t],earliest)
        assert prefix[t]==full[t]
        assert pe==[e for e in events if e['time_ms']<=t]
    counts=dict(points=len(points),snapshot_unknown=sum(p['snapshot_context']['side'] is None for p in points),
        fixed_unknown=sum(p['fixed_memory']['side'] is None for p in points),
        update_only_unknown=sum(p['updated_only']['side'] is None for p in points),
        guarded_unknown=sum(p['guarded']['side'] is None for p in points),
        fixed_changed=sum(p['fixed_memory']['side']!=p['guarded']['side'] for p in points),
        snapshot_changed=sum(p['snapshot_context']['side']!=p['guarded']['side'] for p in points),
        initial_direction_difference=sum(p['guarded']['side']!=p['reset_guarded']['side'] for p in points),
        initial_basis_difference=sum(basis_key(p['updated_only'])!=basis_key(p['reset_updated_only']) for p in points))
    trace=[]
    if old['label']=='original_nine':
        for days,p in zip(cfg['history_days'],prepared):
            for m,scale in p['scales'].items():
                trace.extend(dict(history_days=days,minutes=m,**e) for e in scale['trial']['events']
                             if stamp('2026-08-14T00:00:00Z')<=e['available_ms']<=end)
        trace.sort(key=lambda e:(e['available_ms'],e['history_days'],e['minutes']))
    print(json.dumps(dict(label=old['label'],**counts)),flush=True)
    return dict(label=old['label'],start_ms=start,end_ms=end,points=points,counts=counts,
                events=events,reset_events=cold_events,original_structure_trace=trace)


def render(result):
    lines=['# 같은 계보 기준 갱신·현재 지지 구조 검토','',
           '모든 결과는 개발 자료의 연구 가설이다. 현재 방향 필드는 시장 정답·보유 지시가 아니며 신규 노출 승인은 항상 false다.','',
           '| 사례 | 이전 미판정 | 고정 기억 | 갱신만 | 갱신+지지 | 초기화 방향/기준 차이 |',
           '| --- | ---: | ---: | ---: | ---: | ---: |']
    for c in result['cases']:
        n=c['counts'];lines.append(f"| {c['label']} | {n['snapshot_unknown']} | {n['fixed_unknown']} | {n['update_only_unknown']} | {n['guarded_unknown']}/{n['points']} | {n['initial_direction_difference']}/{n['initial_basis_difference']} |")
    for c in result['cases']:
        lines+=['','## '+c['label'],'','| UTC | 이전 방향 | 고정 기억 | 갱신 기준 | 갱신+지지 방향 | 이유 |','| --- | --- | --- | --- | --- | --- |']
        for p in c['points']:
            root=p['updated_only']['root'];price=None if root is None else root['candidate']['protected']['price']
            lines.append(f"| {p['utc']} | {p['snapshot_context']['side']} | {p['fixed_memory']['side']} | {price} | {p['guarded']['side']} | {p['guarded']['reason']} |")
        if c['original_structure_trace']:
            lines+=['','### 원래 사례 사건표 — UTC','','| 시각 | 이력/창(분) | 사건 | 방향 | 새 반응 가격 또는 무효화 기준 ID | 종가 |','| --- | --- | --- | --- | --- | --- |']
            for e in c['original_structure_trace']:
                lines.append(f"| {utc(e['available_ms'])} | {e['history_days']}일/{e['minutes']} | {e['action']} | {e['side']} | {e.get('protected',{}).get('price',e.get('protected_id'))} | {e.get('close')} |")
    lines+=['','4단계 미통과. 같은 계보 갱신과 지지 구조의 충분성, 주된 전환·매물대·시장 종료는 아직 미검증이며 5·6단계는 보류한다.','']
    return '\n'.join(lines)


def main():
    rows,sources=load_rows();cfg=json.loads(CONFIG.read_text())
    oldpath=ROOT/'reports/validation/market_direction_continuity_20260919/review.json'
    old=json.loads(oldpath.read_text());cases=[run_case(rows,cfg,c) for c in old['cases']]
    sources += [CONFIG,DOC,Path(__file__),oldpath,ROOT/'scripts/review_market_direction_continuity.py',
        ROOT/'scripts/review_market_judgment_regimes.py',ROOT/'app/research/recovery/structure_review.py',
        ROOT/'app/research/recovery/protected_structure.py']
    result=dict(status='development_basis_revision_trial',promotion='not_approved',orders_generated=0,
        new_exposure_allowed=False,cases=cases,checks=dict(truncated_rebuild='PASS'),
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (OUT/'review.md').write_text(render(result))


if __name__=='__main__':main()
